# =========================================================
# DENGUEWATCH - VIEWS.PY
# =========================================================

import csv
import json
import re

from datetime import date, datetime
from pathlib import Path
from collections import Counter

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_GET, require_POST

from .models import (
    UserAccount,
    DengueCase,
    DengueDatasetRecordOverride,
    Barangay,
    Purok,
    CommunityReport,
    Alert,
    SystemNotification,
    notify_user,
    log_report_action,
    ReportAuditLog,
)
from .ml.service import prediction_context
from .locations import ILIGAN_BARANGAYS, canonicalize_barangay, is_iligan_city


# =========================================================
# ROLE ACCESS HELPER
# =========================================================

def role_required(*allowed_roles):
    """
    Restrict a view to specific user roles.

    Example:
        @role_required('CHO')
        @role_required('CHO', 'CHW', 'BHW')
        @role_required('LGU')
    """

    def decorator(view_func):

        @login_required(login_url='login')
        def wrapper(request, *args, **kwargs):

            user_role = getattr(
                request.user,
                'role',
                None
            )

            if user_role not in allowed_roles:

                messages.error(
                    request,
                    'You are not authorized to access this page.'
                )

                return redirect('dashboard')

            if user_role == 'CHO' and not getattr(request.user, 'email_verified', False):
                messages.warning(
                    request,
                    'Verify your email address before using CHO administration features. '
                    'Use the resend verification link if you need a new email.',
                )
                return redirect('resend_verification')

            return view_func(
                request,
                *args,
                **kwargs
            )

        return wrapper

    return decorator


# =========================================================
# HOME
# =========================================================

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')


# =========================================================
# REGISTER
# =========================================================

def register(request):

    if request.user.is_authenticated:

        return redirect('dashboard')

    if request.method == 'POST':

        first_name = request.POST.get(
            'first_name',
            ''
        ).strip()

        last_name = request.POST.get(
            'last_name',
            ''
        ).strip()

        username = request.POST.get(
            'username',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip()

        contact_number = request.POST.get(
            'contact_number',
            ''
        ).strip()

        address = request.POST.get(
            'address',
            ''
        ).strip()

        role = request.POST.get(
            'role',
            ''
        ).strip()

        password1 = request.POST.get(
            'password1',
            ''
        )

        password2 = request.POST.get(
            'password2',
            ''
        )

        # -------------------------------------------------
        # REQUIRED FIELDS
        # -------------------------------------------------

        if not first_name or not last_name:

            messages.error(
                request,
                'Please enter your first and last name.'
            )

            return redirect('register')

        if not username:

            messages.error(
                request,
                'Username is required.'
            )

            return redirect('register')

        if not email:

            messages.error(
                request,
                'Email address is required.'
            )

            return redirect('register')

        if not role:

            messages.error(
                request,
                'Please select your role.'
            )

            return redirect('register')

        # -------------------------------------------------
        # VALID ROLE
        # -------------------------------------------------

        allowed_roles = [
            'CHO',
            'CHW',
            'BHW',
            'LGU'
        ]

        if role not in allowed_roles:

            messages.error(
                request,
                'Invalid role selected.'
            )

            return redirect('register')

        # -------------------------------------------------
        # USERNAME
        # -------------------------------------------------

        if UserAccount.objects.filter(
            username=username
        ).exists():

            messages.error(
                request,
                'Username already exists.'
            )

            return redirect('register')

        # -------------------------------------------------
        # EMAIL
        # -------------------------------------------------

        if UserAccount.objects.filter(
            email=email
        ).exists():

            messages.error(
                request,
                'Email is already registered.'
            )

            return redirect('register')

        # -------------------------------------------------
        # PASSWORD
        # -------------------------------------------------

        if len(password1) < 8:

            messages.error(
                request,
                'Password must contain at least 8 characters.'
            )

            return redirect('register')

        if password1 != password2:

            messages.error(
                request,
                'Passwords do not match.'
            )

            return redirect('register')

        # -------------------------------------------------
        # CREATE ACCOUNT
        # -------------------------------------------------

        user = UserAccount.objects.create(

            username=username,

            email=email,

            first_name=first_name,

            last_name=last_name,

            contact_number=contact_number,

            address=address,

            role=role,

            account_status='PENDING',

            # CHO self-registration is email-verified by this workflow; access
            # still remains disabled until an administrator approves the account.
            email_verified=(role == 'CHO'),

            password=make_password(
                password1
            ),

            is_active=False
        )

        if role == 'CHO':
            messages.success(
                request,
                'CHO account email marked as verified. The account remains pending administrator approval before sign-in is allowed.',
            )
        else:
            # Other staff accounts must confirm email ownership before approval.
            from .api import _send_email_verification
            verification_sent = _send_email_verification(user, request)

            if verification_sent:
                messages.success(request, 'Registration submitted. Check your email and verify your address; CHO approval follows verification.')
            else:
                messages.warning(request, 'Registration was saved, but the verification email could not be sent. Resend it below or contact the system administrator.')

        return redirect('login')

    return render(
        request,
        'register.html'
    )


def resend_verification(request):
    """Send a fresh verification link without disclosing whether an account exists."""
    if request.method == 'POST':
        if not settings.EMAIL_DELIVERY_ENABLED:
            messages.error(request, 'DengueWatch email delivery is not configured on this server yet. Contact the system administrator.')
            return render(request, 'resend_verification.html')
        email = request.POST.get('email', '').strip()
        user = UserAccount.objects.filter(email__iexact=email).exclude(role='RESIDENT').first()
        if user and not user.email_verified:
            from .api import _send_email_verification
            _send_email_verification(user, request)
        messages.info(request, 'If that address belongs to an unverified DengueWatch staff account, a verification email has been sent.')
        return redirect('login')
    return render(request, 'resend_verification.html')


# =========================================================
# LOGIN
# =========================================================

def login_view(request):

    if request.user.is_authenticated:

        return redirect('dashboard')

    if request.method == 'POST':

        username = request.POST.get(
            'username',
            ''
        ).strip()

        password = request.POST.get(
            'password',
            ''
        )

        user = authenticate(
            request,
            username=username,
            password=password
        )

        # Allow the registered email as an alternative sign-in identifier.
        # Django's default backend authenticates by username, so resolve the
        # email to its account username first.
        account = UserAccount.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).order_by('pk').first() if username else None
        if user is None and account and account.email and account.email.casefold() == username.casefold():
            user = authenticate(
                request,
                username=account.username,
                password=password,
            )

        if user is None:

            # Django's ModelBackend intentionally returns None for inactive
            # users. Check a matching account's password only to show its real
            # verification/approval state; never create a session here.
            if account and account.check_password(password):
                if not account.email_verified:
                    messages.error(
                        request,
                        'Your password is correct, but this account must verify its registered email before continuing. '
                        'Use “Resend staff email verification” if the message is missing.',
                    )
                elif account.account_status == 'PENDING':
                    messages.warning(
                        request,
                        'Your email and password are correct, but this account is still pending CHO approval.',
                    )
                elif account.account_status == 'REJECTED':
                    messages.error(request, 'This registration request was rejected.')
                else:
                    messages.error(
                        request,
                        'This account is disabled. Ask a DengueWatch administrator to review its access.',
                    )
                return render(request, 'login.html')

            messages.error(
                request,
                'No account matched that username or email and password. You can sign in with either your username or registered email.'
            )

            return render(
                request,
                'login.html'
            )

        # Residents use only the React Native mobile application.
        # The desktop web system is reserved for health and LGU personnel.
        if user.role == 'RESIDENT':

            messages.error(
                request,
                'Resident accounts can only sign in through the '
                'DengueWatch mobile application.'
            )

            return render(
                request,
                'login.html'
            )

        # A CHO account must prove control of its registered email before
        # entering the admin system, even if an account was previously marked
        # approved by an older workflow.
        if user.role == 'CHO' and not user.email_verified:
            messages.error(
                request,
                'This CHO account cannot continue until its email address is verified. '
                'Open the verification link sent by DengueWatch, or use “Resend staff email verification”.',
            )
            return render(request, 'login.html')

        # -------------------------------------------------
        # ACCOUNT STATUS
        # -------------------------------------------------

        if user.account_status == 'PENDING':

            messages.warning(
                request,
                'Your account is still pending approval. '
                'Please wait for the City Health Office.'
            )

            return render(
                request,
                'login.html'
            )

        if user.account_status == 'REJECTED':

            messages.error(
                request,
                'Your registration request was rejected.'
            )

            return render(
                request,
                'login.html'
            )

        if user.account_status != 'APPROVED':

            messages.error(
                request,
                'Your account is not authorized to access DengueWatch.'
            )

            return render(
                request,
                'login.html'
            )

        # -------------------------------------------------
        # LOGIN
        # -------------------------------------------------

        login(
            request,
            user
        )

        return redirect('dashboard')

    return render(
        request,
        'login.html'
    )


# =========================================================
# DASHBOARD ROUTER
# =========================================================

@login_required(login_url='login')
def dashboard(request):

    role = getattr(
        request.user,
        'role',
        None
    )

    if role == 'CHO':

        return redirect(
            'cho_dashboard'
        )

    elif role == 'CHW':

        return redirect(
            'chw_dashboard'
        )

    elif role == 'BHW':

        return redirect(
            'bhw_dashboard'
        )

    elif role == 'LGU':

        return redirect(
            'lgu_dashboard'
        )

    messages.error(
        request,
        'Your account has no valid assigned role.'
    )

    logout(request)

    return redirect('login')


# =========================================================
# CHO DASHBOARD
# CHO ONLY
# =========================================================

@role_required('CHO')
def cho_dashboard(request):

    cases_data = load_dengue_cases()

    # -----------------------------------------------------
    # TOTAL CASES
    # -----------------------------------------------------

    total_cases = len(
        cases_data
    )

    # -----------------------------------------------------
    # CURRENT YEAR
    # -----------------------------------------------------

    current_year_cases = sum(
        1
        for case in cases_data
        if str(
            case.get('year', '')
        ) == str(timezone.localdate().year)
    )

    # -----------------------------------------------------
    # PENDING USERS
    # -----------------------------------------------------

    pending_users = UserAccount.objects.filter(
        account_status='PENDING'
    ).count()

    # CHW reports become official case counts only after the CHO confirms
    # them. Keep the review queue visible to the final verifier, while the
    # confirmed count makes the live-data flow explicit on this dashboard.
    pending_case_reviews = DengueCase.objects.filter(
        user_account__role='CHW',
        case_status='Pending',
    ).count()

    confirmed_web_cases = DengueCase.objects.filter(
        user_account__role='CHW',
        case_status='Confirmed',
    ).count()

    # -----------------------------------------------------
    # LOCATION COUNTS
    # -----------------------------------------------------

    location_counts = Counter()

    for case in cases_data:

        barangay = str(
            case.get(
                'barangay',
                ''
            )
        ).strip()

        purok = str(
            case.get(
                'purok',
                ''
            )
        ).strip()

        if not barangay:

            barangay = 'Unknown Barangay'

        if not purok:

            purok = (
                'Unknown Sitio / Purok / Street'
            )

        location_counts[
            (
                barangay,
                purok
            )
        ] += 1

    monitored_locations = len(
        location_counts
    )

    high_risk_count = sum(
        1
        for count in location_counts.values()
        if count >= 5
    )

    predicted_hotspots = sum(
        1
        for count in location_counts.values()
        if count >= 5
    )

    context = {

        'total_cases':
            total_cases,

        'dataset_quality': _dataset_quality_summary(),

        'current_year_cases':
            current_year_cases,

        'pending_users':
            pending_users,

        'pending_case_reviews':
            pending_case_reviews,

        'confirmed_web_cases':
            confirmed_web_cases,

        'hotspot_count':
            predicted_hotspots,

        'high_risk_count':
            high_risk_count,

        'monitored_locations':
            monitored_locations,
    }

    return render(
        request,
        'cho_dashboard.html',
        context
    )

# =========================================================
# CHO BARANGAY & PUROK MANAGEMENT
# CHO ONLY
# =========================================================

@role_required('CHO')
def barangay_purok(request):

    # ==========================================
    # ALL BARANGAYS
    # ==========================================

    barangay_queryset = (
        Barangay.objects
        .prefetch_related('puroks')
        .all()
        .order_by('barangay_name')
    )

    # IMPORTANT:
    # This is used by dropdowns.
    # Keep ALL barangays here.
    all_barangays = (
        Barangay.objects
        .all()
        .order_by('barangay_name')
    )

    # ==========================================
    # STATISTICS
    # ==========================================

    total_barangays = barangay_queryset.count()

    total_puroks = Purok.objects.count()

    bhw_users = UserAccount.objects.filter(
        role='BHW',
        account_status='APPROVED'
    )

    assigned_bhws = bhw_users.filter(
        assigned_barangay__isnull=False
    ).count()

    unassigned_bhws = bhw_users.filter(
        assigned_barangay__isnull=True
    ).count()

    # ==========================================
    # PAGINATION
    # 50 BARANGAYS PER PAGE
    # ==========================================

    paginator = Paginator(
        barangay_queryset,
        50
    )

    page_number = request.GET.get(
        'page'
    )

    barangays = paginator.get_page(
        page_number
    )

    # ==========================================
    # CONTEXT
    # ==========================================

    context = {

        # Paginated table
        'barangays':
            barangays,

        # ALL barangays for dropdowns
        'all_barangays':
            all_barangays,

        'total_barangays':
            total_barangays,

        'total_puroks':
            total_puroks,

        'assigned_bhws':
            assigned_bhws,

        'unassigned_bhws':
            unassigned_bhws,
    }

    return render(
        request,
        'barangay_purok.html',
        context
    )

# =========================================================
# ADD BARANGAY
# CHO ONLY
# =========================================================

@role_required('CHO')
def add_barangay(request):

    if request.method != 'POST':
        return redirect('barangay_purok')

    barangay_name = request.POST.get(
        'barangay_name',
        ''
    ).strip()

    latitude = request.POST.get(
        'latitude',
        ''
    ).strip()

    longitude = request.POST.get(
        'longitude',
        ''
    ).strip()

    if not barangay_name:

        messages.error(
            request,
            'Barangay name is required.'
        )

        return redirect('barangay_purok')

    if Barangay.objects.filter(
        barangay_name__iexact=barangay_name
    ).exists():

        messages.error(
            request,
            f'Barangay {barangay_name} already exists.'
        )

        return redirect('barangay_purok')

    Barangay.objects.create(
        barangay_name=barangay_name,
        latitude=latitude or None,
        longitude=longitude or None
    )

    messages.success(
        request,
        f'Barangay {barangay_name} was added successfully.'
    )

    return redirect('barangay_purok')


# =========================================================
# UPDATE BARANGAY
# CHO ONLY
# =========================================================

@role_required('CHO')
def update_barangay(request, barangay_id):

    if request.method != 'POST':
        return redirect('barangay_purok')

    barangay = get_object_or_404(
        Barangay,
        barangay_id=barangay_id
    )

    barangay_name = request.POST.get(
        'barangay_name',
        ''
    ).strip()

    latitude = request.POST.get(
        'latitude',
        ''
    ).strip()

    longitude = request.POST.get(
        'longitude',
        ''
    ).strip()

    if not barangay_name:

        messages.error(
            request,
            'Barangay name is required.'
        )

        return redirect('barangay_purok')

    duplicate = (
        Barangay.objects
        .filter(
            barangay_name__iexact=barangay_name
        )
        .exclude(
            barangay_id=barangay.barangay_id
        )
        .exists()
    )

    if duplicate:

        messages.error(
            request,
            'Another Barangay already uses that name.'
        )

        return redirect('barangay_purok')

    barangay.barangay_name = barangay_name
    barangay.latitude = latitude or None
    barangay.longitude = longitude or None

    barangay.save()

    messages.success(
        request,
        f'{barangay.barangay_name} was updated successfully.'
    )

    return redirect('barangay_purok')


# =========================================================
# DELETE BARANGAY
# CHO ONLY
# =========================================================

@role_required('CHO')
def delete_barangay(request, barangay_id):

    if request.method != 'POST':
        return redirect('barangay_purok')

    barangay = get_object_or_404(
        Barangay,
        barangay_id=barangay_id
    )

    barangay_name = barangay.barangay_name

    barangay.delete()

    messages.success(
        request,
        f'Barangay {barangay_name} was deleted.'
    )

    return redirect('barangay_purok')


# =========================================================
# ADD PUROK
# CHO ONLY
# =========================================================

@role_required('CHO')
def add_purok(request):

    if request.method != 'POST':
        return redirect('barangay_purok')

    barangay_id = request.POST.get(
        'barangay'
    )

    purok_name = request.POST.get(
        'purok_name',
        ''
    ).strip()

    if not barangay_id or not purok_name:

        messages.error(
            request,
            'Barangay and Purok name are required.'
        )

        return redirect('barangay_purok')

    barangay = get_object_or_404(
        Barangay,
        barangay_id=barangay_id
    )

    if Purok.objects.filter(
        barangay=barangay,
        purok_name__iexact=purok_name
    ).exists():

        messages.error(
            request,
            f'{purok_name} already exists in '
            f'{barangay.barangay_name}.'
        )

        return redirect('barangay_purok')

    Purok.objects.create(
        barangay=barangay,
        purok_name=purok_name
    )

    messages.success(
        request,
        f'{purok_name} was added to '
        f'{barangay.barangay_name}.'
    )

    return redirect('barangay_purok')


# =========================================================
# UPDATE PUROK
# CHO ONLY
# =========================================================

@role_required('CHO')
def update_purok(request, purok_id):

    if request.method != 'POST':
        return redirect('barangay_purok')

    purok = get_object_or_404(
        Purok,
        purok_id=purok_id
    )

    barangay_id = request.POST.get(
        'barangay'
    )

    purok_name = request.POST.get(
        'purok_name',
        ''
    ).strip()

    if not barangay_id or not purok_name:

        messages.error(
            request,
            'Barangay and Purok name are required.'
        )

        return redirect('barangay_purok')

    barangay = get_object_or_404(
        Barangay,
        barangay_id=barangay_id
    )

    duplicate = (
        Purok.objects
        .filter(
            barangay=barangay,
            purok_name__iexact=purok_name
        )
        .exclude(
            purok_id=purok.purok_id
        )
        .exists()
    )

    if duplicate:

        messages.error(
            request,
            f'{purok_name} already exists in '
            f'{barangay.barangay_name}.'
        )

        return redirect('barangay_purok')

    purok.barangay = barangay
    purok.purok_name = purok_name

    purok.save()

    messages.success(
        request,
        f'{purok.purok_name} was updated successfully.'
    )

    return redirect('barangay_purok')


# =========================================================
# DELETE PUROK
# CHO ONLY
# =========================================================

@role_required('CHO')
def delete_purok(request, purok_id):

    if request.method != 'POST':
        return redirect('barangay_purok')

    purok = get_object_or_404(
        Purok,
        purok_id=purok_id
    )

    purok_name = purok.purok_name

    purok.delete()

    messages.success(
        request,
        f'{purok_name} was deleted successfully.'
    )

    return redirect('barangay_purok')


# =========================================================
# DENGUE DATASET HELPER
# =========================================================

def load_dengue_cases():

    """
    Load official historical CSV cases plus CHO-confirmed web reports from:

        BASE_DIR / datasets

    Expected fields include:

        Sex
        AgeYears
        Blood Type
        Year
        DAdmit
        (Current Address) Barangay
        (Current Address) Sitio / Purok / Street Name
        (Current Address) City / Municipality
    """

    dataset_folder = (
        Path(settings.BASE_DIR)
        / 'datasets'
    )

    cases_data = []
    dataset_overrides = {
        override.source_record_id: override
        for override in DengueDatasetRecordOverride.objects.all()
    }

    # Use only the uploaded CHO master dataset. Other CSV/XLSX files in the
    # datasets folder are archived references and are never fallback inputs.
    authoritative = dataset_folder / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv'
    csv_files = [authoritative] if authoritative.is_file() else []

    case_id = 1

    for csv_file in csv_files:

        try:

            with open(
                csv_file,
                'r',
                encoding='utf-8-sig',
                newline=''
            ) as csvfile:

                reader = csv.DictReader(
                    csvfile
                )

                for row in reader:

                    override = dataset_overrides.get(case_id)
                    if override and override.is_deleted:
                        case_id += 1
                        continue

                    # -----------------------------------------
                    # SEX
                    # -----------------------------------------

                    sex = (
                        row.get('Sex')
                        or row.get('sex')
                        or ''
                    ).strip()

                    # -----------------------------------------
                    # AGE
                    # -----------------------------------------

                    age = (
                        row.get('AgeYears')
                        or row.get('Age')
                        or row.get('age')
                        or ''
                    ).strip()

                    # -----------------------------------------
                    # CITY / MUNICIPALITY
                    # -----------------------------------------

                    address = (
                        row.get(
                            '(Current Address) City / Municipality'
                        )
                        or row.get(
                            'Current Address'
                        )
                        or row.get(
                            'address'
                        )
                        or ''
                    ).strip()

                    # -----------------------------------------
                    # BARANGAY
                    # -----------------------------------------

                    barangay_raw = (
                        row.get(
                            '(Current Address) Barangay'
                        )
                        or row.get(
                            'Barangay'
                        )
                        or row.get(
                            'barangay'
                        )
                        or ''
                    ).strip()
                    barangay = canonicalize_barangay(barangay_raw)
                    if barangay is None:
                        # Keep source records visible in the line list even
                        # when their location is blank or outside the mapped
                        # study area. Hotspot aggregation still requires an
                        # official Iligan barangay.
                        barangay = barangay_raw or 'Not provided'

                    # -----------------------------------------
                    # PUROK
                    # -----------------------------------------

                    purok = (
                        row.get(
                            '(Current Address) Sitio / Purok / Street Name'
                        )
                        or row.get(
                            'Purok'
                        )
                        or row.get(
                            'purok'
                        )
                        or row.get(
                            'Sitio'
                        )
                        or row.get(
                            'Street'
                        )
                        or ''
                    ).strip()

                    # -----------------------------------------
                    # YEAR
                    # -----------------------------------------

                    year = (
                        row.get('Year')
                        or row.get('year')
                        or ''
                    ).strip()

                    # -----------------------------------------
                    # BLOOD TYPE
                    # -----------------------------------------

                    bloodtype = (
                        row.get('Blood Type')
                        or row.get('Bloodtype')
                        or row.get('BloodType')
                        or row.get('bloodtype')
                        or row.get('blood_type')
                        or ''
                    ).strip()

                    if not bloodtype:

                        bloodtype = 'N/A'

                    birthdate = (
                        row.get('Birthdate')
                        or row.get('Birth Date')
                        or row.get('Date of Birth')
                        or row.get('birth_date')
                        or row.get('birthday')
                        or ''
                    ).strip()

                    # -----------------------------------------
                    # DATE REPORTED
                    # -----------------------------------------

                    date_reported = (
                        row.get('DAdmit')
                        or row.get('Date Reported')
                        or row.get('date_reported')
                        or ''
                    ).strip()

                    if not date_reported:

                        date_reported = 'Not provided'

                    # -----------------------------------------
                    # SAVE CASE
                    # -----------------------------------------

                    case_record = {

                        'id':
                            case_id,

                        'record_type':
                            'dataset',

                        'record_id':
                            case_id,

                        'display_id':
                            f'DW-{case_id:04d}',

                        'sex':
                            sex,

                        'age':
                            age,

                        'blood_type':
                            bloodtype,

                        'birthdate':
                            birthdate or 'Not provided',

                        'address':
                            address,

                        'barangay':
                            barangay,

                        'purok':
                            purok,

                        'year':
                            year,

                        'date_reported':
                            date_reported,

                        'source_file':
                            csv_file.name,
                    }
                    if override:
                        editable_fields = {
                            'sex', 'age', 'blood_type', 'birthdate', 'address',
                            'barangay', 'purok', 'year', 'date_reported',
                        }
                        case_record.update({
                            key: value
                            for key, value in override.overrides.items()
                            if key in editable_fields
                        })
                    cases_data.append(case_record)

                    case_id += 1

        except (
            OSError,
            csv.Error
        ):

            continue

    # CHW submissions remain private workflow records until CHO marks them
    # Confirmed. Only those CHO-confirmed records are added to the aggregate
    # views used by dashboards, maps, and resident public summaries.
    confirmed_cases = DengueCase.objects.filter(
        case_status='Confirmed',
        barangay__isnull=False,
    ).exclude(
        # The importer copied workbook rows that are already represented by
        # the historical CSV exports loaded above. Keep the source rows in
        # storage, but exclude this marked copy from totals and case lists.
        user_account__username='dataset_importer',
        remarks__istartswith='Imported from workbook',
    ).select_related('barangay', 'purok').order_by('dengue_case_id')

    next_display_case_id = case_id
    for report in confirmed_cases:
        barangay = canonicalize_barangay(report.barangay.barangay_name)
        if not barangay:
            continue
        copies = max(1, int(report.case_count or 1))
        for copy_index in range(copies):
            cases_data.append({
                'id': f'confirmed-{report.dengue_case_id}-{copy_index + 1}',
                'record_type': 'system',
                'record_id': report.dengue_case_id,
                'display_id': f'DW-{next_display_case_id:04d}',
                'sex': report.patient_sex,
                'age': report.patient_age,
                'blood_type': report.patient_blood_type or 'N/A',
                'birthdate': report.patient_birth_date.strftime('%m/%d/%Y') if report.patient_birth_date else 'Not provided',
                'address': 'Iligan City',
                'barangay': barangay,
                'purok': report.purok.purok_name if report.purok else 'Not specified',
                'location_details': report.location_details,
                'year': str(report.date_reported.year),
                'date_reported': report.date_reported.isoformat(),
                'source_file': 'CHO-confirmed web record',
            })
            next_display_case_id += 1

    return cases_data


def build_report_analytics(selected_year='all'):
    """Create demographic and yearly summaries from the historical CSVs."""
    cases = load_dengue_cases()
    if selected_year and str(selected_year).lower() != 'all':
        cases = [case for case in cases if str(case.get('year')) == str(selected_year)]
    yearly = Counter()
    sex = Counter()
    blood_types = Counter()
    age_groups = Counter()
    for case in cases:
        yearly[str(case.get('year') or 'Unknown')] += 1
        sex[str(case.get('sex') or 'Not specified').title()] += 1
        blood = str(case.get('blood_type') or 'N/A').upper()
        blood_types[blood] += 1
        try:
            age = int(float(case.get('age')))
            group = '0–5' if age <= 5 else '6–12' if age <= 12 else '13–19' if age <= 19 else '20–39' if age <= 39 else '40–59' if age <= 59 else '60+'
        except (TypeError, ValueError):
            group = 'Unknown'
        age_groups[group] += 1
    return {
        'yearly_summary': sorted(yearly.items(), reverse=True),
        'sex_summary': sex.most_common(),
        'blood_type_summary': blood_types.most_common(),
        'age_group_summary': age_groups.most_common(),
    }


def _dataset_quality_summary():
    """Return aggregate-only quality counts for public-facing data notes."""
    path = Path(settings.BASE_DIR) / 'datasets' / 'dengue_dataset_quality.json'
    try:
        quality = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    historical_manifest_path = Path(settings.BASE_DIR) / 'datasets' / 'cho_historical' / 'manifest.json'
    try:
        historical_manifest = json.loads(historical_manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        historical_manifest = {}
    historical_sources = historical_manifest.get('historical_datasets', {})
    historical_rows = sum(item.get('rows', 0) for item in historical_sources.values())
    inventory_path = Path(settings.BASE_DIR) / 'datasets' / 'data_feasibility_inventory.json'
    try:
        inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        inventory = {}
    patient_audit = inventory.get('patient_line_list', {})
    monthly_audit = inventory.get('monthly_model_dataset', {})
    completeness = inventory.get('case_reporting_completeness_confirmation', {})
    synthetic_manifest_path = Path(settings.BASE_DIR) / 'datasets' / 'synthetic_supplement' / 'manifest.json'
    try:
        synthetic_manifest = json.loads(synthetic_manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        synthetic_manifest = {}
    return {
        'source_rows': quality.get('source_row_count', 0),
        'complete_rows': quality.get('rows_complete_across_all_eight_requested_fields', 0),
        'rows_with_gaps': quality.get('rows_with_one_or_more_missing_requested_fields', 0),
        'exact_duplicate_extra_rows': quality.get('exact_duplicate_extra_rows', 0),
        'year_mismatches': quality.get('admission_date_year_mismatch_rows', 0),
        'rows_without_official_barangay': quality.get('rows_without_official_iligan_barangay_match', 0),
        'historical_cho_rows': historical_rows,
        'historical_cho_years': sorted(historical_sources),
        'admission_date_range': quality.get('admission_date_range', []),
        'valid_admission_date_rows': quality.get('admission_date_valid_rows', 0),
        'missing_admission_date_rows': quality.get(
            'admission_date_missing_or_invalid_rows',
            quality.get('admission_date_missing_rows', 0),
        ),
        'outside_iligan_city_rows': quality.get('outside_iligan_city_rows', 0),
        'application_year_policy': quality.get('application_year_policy', ''),
        'admission_year_mismatches': quality.get('admission_date_year_mismatch_rows', 0),
        'exact_duplicate_group_rows': quality.get('rows_in_exact_duplicate_groups', 0),
        'potential_duplicate_matches': patient_audit.get('potential_duplicate_matches', 0),
        'duplicate_policy': patient_audit.get('duplicate_policy', 'Exact duplicate rows are retained and flagged.'),
        'case_definition_status': 'CHO source verified by the project team; the source file does not contain a case-definition version or confirmed/suspected status field.',
        'reporting_delay_status': 'Not measurable from this source: it has admission dates but no received/entered dates.',
        'zero_month_cells': monthly_audit.get('cells_with_zero_under_user_completeness_confirmation', 0),
        'zero_month_interpretation': monthly_audit.get('zero_semantics', ''),
        'zero_reporting_status': completeness.get('status', 'Not documented'),
        'synthetic_rows_excluded': synthetic_manifest.get('total_rows', 0),
        'active_case_source_status': 'CHO-verified source data (confirmed by the project team)',
        'source_history_notice': (
            f"{historical_rows:,} CHO-verified 2018–2019 records are included in the consolidated source. Exact duplicate and unmatched-barangay rows are retained and flagged; official barangay maps exclude records without an official Iligan barangay match."
            if historical_manifest else ''
        ),
    }

# =========================================================
# LGU HOTSPOT MAP
# LGU ONLY
# =========================================================

@role_required('LGU')
@require_GET
def lgu_hotspot_map(request):

    # Use EXACTLY the same hotspot processing
    # as the CHO hotspot map.

    context = build_hotspot_data(request)
    return render(
        request,
        'lgu_hotspot_map.html',
        context
    )


# =========================================================
# SHARED CHO / CHW HOTSPOT MAP
# =========================================================

@role_required('CHO', 'CHW')
def hotspot_map(request):

    context = build_hotspot_data(
        request
    )
    return render(
        request,
        'hotspot_map.html',
        context
    )


@role_required('CHO', 'CHW', 'LGU')
@require_GET
def hotspot_map_data(request):
    """Return freshly aggregated confirmed-case map data for live map refresh."""
    context = build_hotspot_data(request)
    return JsonResponse({
        'map_data': json.loads(context['map_locations_json']),
        'total_cases': context['total_cases'],
        'high_risk_areas': context['high_risk_areas'],
        'predicted_hotspots': context['predicted_hotspots'],
        'current_month_label': context['current_month_label'],
        'current_month_case_total': context['current_month_case_total'],
        'current_month_report_count': context['current_month_report_count'],
        'current_month_top_barangays': context['current_month_top_barangays'],
        'refreshed_at': timezone.localtime().isoformat(),
    })


# =========================================================
# AI PREDICTIONS
# CHO ONLY
# =========================================================

@role_required('CHO')
def predictions(request):
    """CHO read-only AI prediction page."""
    context = prediction_context(request)
    context['page_role'] = 'CHO'
    return render(
        request,
        'cho_ai_prediction.html',
        context,
    )


@role_required('LGU')
@require_GET
def lgu_ai_predictions(request):
    """LGU read-only AI prediction page."""
    context = prediction_context(request)
    context['page_role'] = 'LGU'
    return render(
        request,
        'lgu_ai_prediction.html',
        context,
    )


# =========================================================
# REPORTS & ANALYTICS
# CHO ONLY
# =========================================================

@role_required('CHO')
def reports(request):
    context = build_hotspot_data(request)
    context.update(build_report_analytics())
    context['report_title'] = 'CHO Reports and Analytics'
    return render(request, 'reports.html', context)


@role_required('LGU')
@require_GET
def lgu_reports(request):
    """
    LGU Reports & Analytics
    Displays dengue reports based only on LGU-accessible data.
    """

    selected_year = request.GET.get('year', 'all').strip()
    context = build_hotspot_data(request)
    context.update(build_report_analytics(selected_year))
    context['report_title'] = 'LGU Reports and Analytics'
    context['selected_year'] = selected_year
    return render(request, 'lgu_reports_analytics.html', context)


@role_required('LGU')
@require_GET
def lgu_dengue_reports(request):
    """Search, filter, print, and export de-identified, city-wide planning reports."""
    all_cases = load_dengue_cases()
    years = sorted(
        {str(case.get('year')) for case in all_cases if case.get('year')},
        reverse=True,
    )
    barangays = sorted(
        {str(case.get('barangay')) for case in all_cases if case.get('barangay')},
        key=str.lower,
    )

    search = request.GET.get('search', '').strip()
    selected_year = request.GET.get('year', 'all').strip()
    selected_barangay = request.GET.get('barangay', 'all').strip()
    filtered_cases = all_cases

    if selected_year.lower() != 'all':
        filtered_cases = [
            case for case in filtered_cases
            if str(case.get('year')) == selected_year
        ]
    if selected_barangay.lower() != 'all':
        filtered_cases = [
            case for case in filtered_cases
            if str(case.get('barangay', '')).lower() == selected_barangay.lower()
        ]
    if search:
        needle = search.lower()
        searchable_fields = ('barangay', 'purok', 'sex', 'age', 'blood_type', 'date_reported')
        filtered_cases = [
            case for case in filtered_cases
            if any(needle in str(case.get(field, '')).lower() for field in searchable_fields)
        ]

    filtered_cases = sorted(
        filtered_cases,
        key=lambda case: (str(case.get('year', '')), str(case.get('date_reported', ''))),
        reverse=True,
    )

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="denguewatch_lgu_report.csv"'
        writer = csv.writer(response)
        writer.writerow(['Record ID', 'Year', 'Date Reported', 'Barangay', 'Purok', 'Sex', 'Age', 'Blood Type'])
        for case in filtered_cases:
            writer.writerow([
                case.get('id'), case.get('year'), case.get('date_reported'),
                case.get('barangay'), case.get('purok'), case.get('sex'),
                case.get('age'), case.get('blood_type'),
            ])
        return response

    paginator = Paginator(filtered_cases, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'page_obj': page_obj,
        'years': years,
        'barangays': barangays,
        'search': search,
        'selected_year': selected_year,
        'selected_barangay': selected_barangay,
        'total_records': len(all_cases),
        'filtered_count': len(filtered_cases),
        'barangay_count': len({case.get('barangay') for case in filtered_cases if case.get('barangay')}),
    }
    return render(request, 'lgu_dengue_reports.html', context)

# =========================================================
# DENGUE CASES
# CHO / CHW / BHW ONLY
# =========================================================

@role_required(
    'CHO',
    'CHW',
)
def cases(request):

    cases_data = load_dengue_cases()

    # =====================================================
    # BHW - ONLY ASSIGNED BARANGAY
    # =====================================================

    if getattr(
        request.user,
        'role',
        None
    ) == 'BHW':

        assigned_barangay_object = getattr(
            request.user,
            'assigned_barangay',
            None
        )

        if assigned_barangay_object:

            assigned_barangay = getattr(
                assigned_barangay_object,
                'barangay_name',
                str(assigned_barangay_object)
            )

            assigned_barangay = str(
                assigned_barangay
            ).strip().lower()

            cases_data = [
                case
                for case in cases_data
                if str(
                    case.get(
                        'barangay',
                        ''
                    )
                ).strip().lower()
                == assigned_barangay
            ]

        else:

            # No assigned barangay means a BHW must not
            # receive unrestricted city-wide case records.
            cases_data = []

    # =====================================================
    # FILTERS
    # =====================================================

    search = request.GET.get(
        'search',
        ''
    ).strip().lower()

    sex_filter = request.GET.get(
        'sex',
        ''
    ).strip().lower()

    age_filter = request.GET.get(
        'age',
        ''
    ).strip()

    year_filter = request.GET.get(
        'year',
        ''
    ).strip()

    blood_filter = request.GET.get(
        'blood_type',
        ''
    ).strip().lower()

    # =====================================================
    # FILTER CASES
    # =====================================================

    filtered_cases = []

    for case in cases_data:

        # -------------------------------------------------
        # SEARCH
        # -------------------------------------------------

        if search:

            searchable = ' '.join([

                str(
                    case.get(
                        'sex',
                        ''
                    )
                ),

                str(
                    case.get(
                        'age',
                        ''
                    )
                ),

                str(
                    case.get(
                        'blood_type',
                        ''
                    )
                ),

                str(
                    case.get(
                        'address',
                        ''
                    )
                ),

                str(
                    case.get(
                        'barangay',
                        ''
                    )
                ),

                str(
                    case.get(
                        'purok',
                        ''
                    )
                ),

                str(
                    case.get(
                        'year',
                        ''
                    )
                ),

                str(
                    case.get(
                        'date_reported',
                        ''
                    )
                ),

            ]).lower()

            if search not in searchable:

                continue

        # -------------------------------------------------
        # SEX
        # -------------------------------------------------

        if sex_filter:

            if (
                case.get(
                    'sex',
                    ''
                ).lower()
                != sex_filter
            ):

                continue

        # -------------------------------------------------
        # AGE
        # -------------------------------------------------

        if age_filter:

            if str(
                case.get(
                    'age',
                    ''
                )
            ) != age_filter:

                continue

        # -------------------------------------------------
        # YEAR
        # -------------------------------------------------

        if year_filter:

            if str(
                case.get(
                    'year',
                    ''
                )
            ) != year_filter:

                continue

        # -------------------------------------------------
        # BLOOD TYPE
        # -------------------------------------------------

        if blood_filter:

            if (
                case.get(
                    'blood_type',
                    ''
                ).lower()
                != blood_filter
            ):

                continue

        filtered_cases.append(
            case
        )

    def case_reported_date(case):
        raw_date = str(case.get('date_reported', '')).strip()
        if not raw_date or raw_date == 'Not provided':
            return date.min
        try:
            return date.fromisoformat(raw_date)
        except ValueError:
            for date_format in ('%m/%d/%Y', '%d/%m/%Y', '%b %d, %Y'):
                try:
                    return datetime.strptime(raw_date, date_format).date()
                except ValueError:
                    continue
        return date.min

    # Sort after filtering and before pagination so the newest reported cases
    # appear first on every page, with undated historical rows at the end.
    filtered_cases.sort(
        key=case_reported_date,
        reverse=True,
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    male_cases = sum(

        1
        for case in cases_data

        if case.get(
            'sex',
            ''
        ).lower()
        == 'male'
    )

    female_cases = sum(

        1
        for case in cases_data

        if case.get(
            'sex',
            ''
        ).lower()
        == 'female'
    )

    # =====================================================
    # YEARS
    # =====================================================

    years = sorted(

        {
            str(
                case.get(
                    'year',
                    ''
                )
            )

            for case in cases_data

            if case.get(
                'year',
                ''
            )
        },

        reverse=True
    )

    # =====================================================
    # CURRENT YEAR
    # =====================================================

    current_year_cases = sum(

        1
        for case in cases_data

        if str(
            case.get(
                'year',
                ''
            )
        ) == '2026'
    )

    # =====================================================
    # PAGINATION
    # =====================================================

    paginator = Paginator(
        filtered_cases,
        50
    )

    page_number = request.GET.get(
        'page'
    )

    page_obj = paginator.get_page(
        page_number
    )

    # =====================================================
    # CONTEXT
    # =====================================================

    context = {

        'cases':
            page_obj,

        'page_obj':
            page_obj,

        'paginator':
            paginator,

        'total_cases':
            len(
                filtered_cases
            ),

        'male_cases':
            male_cases,

        'female_cases':
            female_cases,

        'current_year_cases':
            current_year_cases,

        'years':
            years,

        'dataset_quality': _dataset_quality_summary(),
        'edit_barangays': Barangay.objects.all().order_by('barangay_name'),
        'edit_puroks': Purok.objects.select_related('barangay').order_by('barangay__barangay_name', 'purok_name'),
    }

    return render(
        request,
        'cases.html',
        context
    )


def _parse_dengue_case_date(value):
    raw = str(value or '').strip()
    if not raw or raw == 'Not provided':
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        for date_format in ('%m/%d/%Y', '%d/%m/%Y', '%b %d, %Y'):
            try:
                return datetime.strptime(raw, date_format).date()
            except ValueError:
                continue
    return None


def _get_manageable_system_case(record_id):
    return get_object_or_404(
        DengueCase.objects.filter(
            case_status='Confirmed',
            barangay__isnull=False,
        ).exclude(
            user_account__username='dataset_importer',
            remarks__istartswith='Imported from workbook',
        ),
        pk=record_id,
    )


@role_required('CHO')
def edit_dengue_case_record(request, record_type, record_id):
    if record_type == 'dataset':
        record = next((
            item for item in load_dengue_cases()
            if item.get('record_type') == 'dataset'
            and item.get('record_id') == record_id
        ), None)
        if record is None:
            raise Http404('Dataset record not found.')
        is_system = False
    elif record_type == 'system':
        report = _get_manageable_system_case(record_id)
        listed_record = next((
            item for item in load_dengue_cases()
            if item.get('record_type') == 'system'
            and item.get('record_id') == record_id
        ), {})
        record = {
            'display_id': listed_record.get('display_id', f'DW-{record_id:04d}'),
            'sex': report.patient_sex,
            'age': report.patient_age,
            'blood_type': report.patient_blood_type,
            'birthdate': report.patient_birth_date.isoformat() if report.patient_birth_date else '',
            'address': 'Iligan City',
            'barangay': report.barangay.barangay_name,
            'purok': report.purok.purok_name if report.purok else '',
            'year': report.date_reported.year,
            'date_reported': report.date_reported.isoformat(),
            'location_details': report.location_details,
        }
        is_system = True
    else:
        raise Http404('Unknown dengue case record type.')

    errors = []
    if request.method == 'POST':
        sex = request.POST.get('sex', '').strip()
        raw_age = request.POST.get('age', '').strip()
        blood_type = request.POST.get('blood_type', '').strip()
        address = request.POST.get('address', '').strip()
        barangay_name = request.POST.get('barangay', '').strip()
        purok_name = request.POST.get('purok', '').strip()
        raw_birthdate = request.POST.get('birthdate', '').strip()
        raw_reported_date = request.POST.get('date_reported', '').strip()
        location_details = request.POST.get('location_details', '').strip()

        try:
            age = int(raw_age)
            if age < 0 or age > 120:
                raise ValueError
        except ValueError:
            errors.append('Age must be a whole number from 0 to 120.')

        reported_date = _parse_dengue_case_date(raw_reported_date)
        if raw_reported_date and reported_date is None:
            errors.append('Enter a valid reported date.')
        if is_system and reported_date is None:
            errors.append('A reported date is required for CHO-confirmed reports.')
        if not sex:
            errors.append('Sex is required.')
        if len(blood_type) > 5:
            errors.append('Blood type must be 5 characters or fewer.')
        if not barangay_name:
            errors.append('Barangay is required.')

        if is_system:
            barangay = Barangay.objects.filter(barangay_name__iexact=barangay_name).first()
            if barangay is None:
                errors.append('Select an existing Iligan City barangay.')
            purok = None
            if barangay and purok_name:
                purok = Purok.objects.filter(
                    barangay=barangay,
                    purok_name__iexact=purok_name,
                ).first()
                if purok is None:
                    errors.append('Select a purok that belongs to the selected barangay.')
            birthdate = _parse_dengue_case_date(raw_birthdate) if raw_birthdate else None
            if raw_birthdate and birthdate is None:
                errors.append('Enter a valid birthdate.')

        if not errors:
            if is_system:
                report.patient_age = age
                report.patient_sex = sex
                report.patient_blood_type = blood_type
                report.patient_birth_date = birthdate
                report.date_reported = reported_date
                report.barangay = barangay
                report.purok = purok
                report.location_details = location_details
                report.save(update_fields=[
                    'patient_age', 'patient_sex', 'patient_blood_type',
                    'patient_birth_date', 'date_reported', 'barangay',
                    'purok', 'location_details',
                ])
            else:
                override, _ = DengueDatasetRecordOverride.objects.get_or_create(
                    source_record_id=record_id,
                )
                override.overrides = {
                    'sex': sex,
                    'age': age,
                    'blood_type': blood_type or 'N/A',
                    'address': address,
                    'barangay': barangay_name,
                    'purok': purok_name,
                    'year': reported_date.year if reported_date else request.POST.get('year', '').strip(),
                    'date_reported': reported_date.isoformat() if reported_date else 'Not provided',
                    'birthdate': raw_birthdate or 'Not provided',
                }
                override.updated_by = request.user
                override.is_deleted = False
                override.save()
            messages.success(request, f"Case {record['display_id']} was updated.")
            return redirect('cases')

        messages.error(request, ' '.join(errors))
        record = {
            **record,
            'sex': sex,
            'age': raw_age,
            'blood_type': blood_type,
            'address': address,
            'barangay': barangay_name,
            'purok': purok_name,
            'birthdate': raw_birthdate,
            'date_reported': raw_reported_date,
            'location_details': location_details,
        }

    parsed_reported_date = _parse_dengue_case_date(record.get('date_reported'))
    parsed_birthdate = _parse_dengue_case_date(record.get('birthdate'))
    context = {
        'record': record,
        'record_type': record_type,
        'record_id': record_id,
        'is_system': is_system,
        'barangays': Barangay.objects.all().order_by('barangay_name'),
        'puroks': Purok.objects.select_related('barangay').order_by('barangay__barangay_name', 'purok_name'),
        'reported_date_value': parsed_reported_date.isoformat() if parsed_reported_date else '',
        'birthdate_value': parsed_birthdate.isoformat() if parsed_birthdate else '',
    }
    return render(request, 'case_dataset_edit.html', context)


@role_required('CHO')
@require_POST
def delete_dengue_case_record(request, record_type, record_id):
    if record_type == 'dataset':
        override, _ = DengueDatasetRecordOverride.objects.get_or_create(
            source_record_id=record_id,
        )
        override.is_deleted = True
        override.updated_by = request.user
        override.save(update_fields=['is_deleted', 'updated_by', 'updated_at'])
    elif record_type == 'system':
        report = _get_manageable_system_case(record_id)
        report.delete()
    else:
        raise Http404('Unknown dengue case record type.')
    messages.success(request, f'Case record {record_id} was removed from Dengue Cases.')
    return redirect('cases')


# =========================================================
# BHW DENGUE CASE MONITORING
# BHW ONLY
# =========================================================

def _bhw_case_records(user):
    """Combine CHO historical records and reviewed system cases in one BHW area."""
    assigned_barangay = getattr(user, 'assigned_barangay', None)
    if not assigned_barangay:
        return []

    target_barangay = canonicalize_barangay(assigned_barangay.barangay_name)
    if not target_barangay:
        return []

    def normalize(value):
        return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()

    assigned_purok = getattr(user, 'assigned_purok', None)
    target_purok = normalize(assigned_purok.purok_name) if assigned_purok else ''

    def parse_source_date(value):
        raw = str(value or '').strip()
        if not raw or raw == 'Not provided':
            return None
        for date_format in ('%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y', '%b %d, %Y'):
            try:
                return datetime.strptime(raw, date_format).date()
            except ValueError:
                continue
        return None

    records = []
    historical_rows = [
        row for row in load_dengue_cases()
        if row.get('source_file') != 'CHO-confirmed web record'
    ]
    for row in historical_rows:
        if canonicalize_barangay(row.get('barangay')) != target_barangay:
            continue
        if target_purok and normalize(row.get('purok')) != target_purok:
            continue

        try:
            source_id = int(row.get('id'))
        except (TypeError, ValueError):
            source_id = len(records) + 1
        records.append({
            'display_id': f'HIS-{source_id:06d}',
            'modal_id': f'historical-case-{source_id}',
            'patient_sex': row.get('sex') or '',
            'patient_age': row.get('age') or '',
            'patient_blood_type': row.get('blood_type') or '',
            'date_reported': parse_source_date(row.get('date_reported')),
            'case_count': 1,
            'case_status': 'Historical',
            'barangay_name': target_barangay,
            'purok_name': row.get('purok') or 'Not specified',
            'remarks': 'Historical record from the CHO-verified dataset.',
            'source_label': 'CHO historical dataset',
            'reporter_name': 'CHO-verified historical dataset',
            'reporter_username': 'Historical record',
            'is_historical': True,
        })

    new_cases = DengueCase.objects.filter(
        barangay=assigned_barangay,
        case_status__in=['Confirmed', 'Active', 'Recovered'],
    ).exclude(
        user_account__username='dataset_importer',
        remarks__istartswith='Imported from workbook',
    ).select_related('user_account', 'barangay', 'purok').order_by('-date_reported', '-dengue_case_id')
    if assigned_purok:
        new_cases = new_cases.filter(purok=assigned_purok)

    for report in new_cases:
        reporter = report.user_account.get_full_name().strip() or report.user_account.username
        records.append({
            'display_id': f'DW-{report.dengue_case_id:04d}',
            'modal_id': f'system-case-{report.dengue_case_id}',
            'patient_sex': report.patient_sex or '',
            'patient_age': report.patient_age,
            'patient_blood_type': report.patient_blood_type or '',
            'date_reported': report.date_reported,
            'case_count': max(1, int(report.case_count or 1)),
            'case_status': report.case_status,
            'barangay_name': report.barangay.barangay_name,
            'purok_name': report.purok.purok_name if report.purok else 'Not specified',
            'remarks': report.remarks or '',
            'source_label': 'CHO-confirmed system case',
            'reporter_name': reporter,
            'reporter_username': report.user_account.username,
            'is_historical': False,
        })

    records.sort(key=lambda row: row.get('date_reported') or date.min, reverse=True)
    return records


@role_required('BHW')
def dengue_case_bhw(request):

    assigned_barangay = request.user.assigned_barangay
    assigned_purok = request.user.assigned_purok
    area_cases = _bhw_case_records(request.user)

    search = request.GET.get('search', '').strip().casefold()
    selected_status = request.GET.get('status', '').strip()
    selected_sex = request.GET.get('sex', '').strip()
    selected_blood_type = request.GET.get('blood_type', '').strip().upper()

    historical_cases = sum(row['case_count'] for row in area_cases if row['is_historical'])
    new_case_records = sum(row['case_count'] for row in area_cases if not row['is_historical'])
    active_cases = sum(row['case_count'] for row in area_cases if row['case_status'] == 'Active')
    confirmed_cases = sum(row['case_count'] for row in area_cases if row['case_status'] == 'Confirmed')
    recovered_cases = sum(row['case_count'] for row in area_cases if row['case_status'] == 'Recovered')
    current_cases = active_cases + confirmed_cases
    pending_cases = 0

    if selected_status:
        area_cases = [row for row in area_cases if row['case_status'] == selected_status]
    if selected_sex:
        area_cases = [row for row in area_cases if row['patient_sex'].casefold() == selected_sex.casefold()]
    if selected_blood_type:
        area_cases = [row for row in area_cases if row['patient_blood_type'].upper() == selected_blood_type]
    if search:
        area_cases = [
            row for row in area_cases
            if search in ' '.join(str(row.get(key) or '') for key in (
                'display_id', 'patient_sex', 'patient_age', 'patient_blood_type',
                'date_reported', 'case_status', 'barangay_name', 'purok_name',
                'remarks', 'source_label',
            )).casefold()
        ]

    context = {

        'dengue_cases': area_cases,

        'assigned_barangay':
            assigned_barangay,

        'assigned_purok':
            assigned_purok,

        'current_cases':
            current_cases,

        'active_cases':
            active_cases,

        'confirmed_cases':
            confirmed_cases,

        'pending_cases':
            pending_cases,

        'recovered_cases':
            recovered_cases,

        'total_area_cases':
            historical_cases + new_case_records,

        'historical_cases': historical_cases,

        'new_case_records': new_case_records,

        'search': search,

        'selected_status': selected_status,

        'selected_sex': selected_sex,

        'selected_blood_type': selected_blood_type,
    }

    return render(
        request,
        'dengue_case_bhw.html',
        context
    )

# =========================================================
# SHARED HOTSPOT DATA
# USED BY BOTH CHO AND LGU
# =========================================================

def build_hotspot_data(request):
    """
    Build the exact same hotspot data for CHO and LGU.

    Both roles use:
        datasets/WILBUR_DSO_dengue_*.csv

    Risk thresholds:
        1 - 5       = Low
        6 - 50      = Moderate
        51 - 100    = High
        101+        = Critical

    These are DengueWatch display thresholds and are
    NOT official DOH outbreak classifications.
    """

    dataset_dir = (
        Path(settings.BASE_DIR)
        / 'datasets'
    )

    # =====================================================
    # USE THE SAME DATASETS AS CHO HOTSPOT MAP
    # =====================================================

    authoritative = dataset_dir / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv'
    dataset_files = [authoritative] if authoritative.is_file() else []

    # =====================================================
    # FILTERS
    # =====================================================

    selected_year = request.GET.get(
        'year',
        '2026'
    ).strip()

    selected_risk = request.GET.get(
        'risk',
        'all'
    ).strip().lower()

    # =====================================================
    # STORAGE
    # =====================================================

    barangays = {}

    all_years = set()

    total_dataset_cases = 0

    # =====================================================
    # NORMALIZE BARANGAY
    # =====================================================

    def normalize_name(value):

        value = str(
            value or ''
        ).strip()

        value = re.sub(
            r'[-]+',
            ' ',
            value
        )

        value = re.sub(
            r'\s+',
            ' ',
            value
        )

        return value.lower().strip()

    def normalize_year(value):
        """Normalize the dataset's year column, including legacy date values."""
        raw = str(value or '').strip()
        if re.fullmatch(r'\d{4}', raw):
            return raw
        for date_format in ('%m/%d/%Y', '%d/%m/%Y'):
            try:
                return str(datetime.strptime(raw, date_format).year)
            except ValueError:
                continue
        return ''

    # =====================================================
    # RISK LEVEL
    # =====================================================

    def get_risk(case_count):

        if case_count >= 101:
            return 'Critical'

        elif case_count >= 51:
            return 'High'

        elif case_count >= 6:
            return 'Moderate'

        elif case_count >= 1:
            return 'Low'

        return 'None'

    # =====================================================
    # RISK COLOR
    # =====================================================

    def get_risk_color(risk_level):

        if risk_level == 'Critical':
            return '#dc2626'

        elif risk_level == 'High':
            return '#f97316'

        elif risk_level == 'Moderate':
            return '#facc15'

        elif risk_level == 'Low':
            return '#22c55e'

        return '#9ca3af'

    # =====================================================
    # READ DATASETS
    # =====================================================

    for dataset_path in dataset_files:

        try:

            with open(
                dataset_path,
                'r',
                encoding='utf-8-sig',
                newline=''
            ) as csvfile:

                reader = csv.DictReader(
                    csvfile
                )

                for row in reader:

                    total_dataset_cases += 1

                    # =============================================
                    # YEAR
                    # =============================================

                    year = normalize_year(
                        row.get('Year')
                        or row.get('year')
                        or ''
                    )

                    if year:
                        year = str(year)
                        all_years.add(year)

                    # =============================================
                    # BARANGAY
                    # =============================================

                    barangay_raw = (
                        row.get(
                            '(Current Address) Barangay'
                        )
                        or row.get('Barangay')
                        or row.get('barangay')
                        or ''
                    ).strip()
                    barangay = canonicalize_barangay(barangay_raw)
                    if not barangay:
                        # Keep all CHO/LGU/BHW analyses within the official
                        # City of Iligan 44-barangay study scope.
                        continue

                    # =============================================
                    # PUROK / SITIO / STREET
                    # =============================================

                    purok = (
                        row.get(
                            '(Current Address) Sitio / Purok / Street Name'
                        )
                        or row.get('Purok')
                        or row.get('purok')
                        or row.get('Sitio')
                        or row.get('Street')
                        or ''
                    ).strip()

                    if not purok:
                        purok = 'Not specified'

                    # =============================================
                    # CITY
                    # =============================================

                    city = (
                        row.get(
                            '(Current Address) City / Municipality'
                        )
                        or row.get('City')
                        or row.get('city')
                        or ''
                    ).strip()

                    if '(Current Address) City / Municipality' in row and not is_iligan_city(city):
                        total_dataset_cases -= 1
                        continue

                    if not city:
                        city = 'Iligan City'

                    # =============================================
                    # NORMALIZED BARANGAY KEY
                    # =============================================

                    barangay_key = normalize_name(
                        barangay
                    )

                    # =============================================
                    # CREATE BARANGAY
                    # =============================================

                    if barangay_key not in barangays:

                        barangays[barangay_key] = {
                            'barangay': barangay,
                            'city': city,
                            'cases': 0,
                            'puroks': Counter(),
                            'years': Counter(),
                        }

                    # =============================================
                    # CASE COUNT
                    # =============================================

                    barangays[
                        barangay_key
                    ]['cases'] += 1

                    # =============================================
                    # PUROK COUNT
                    # =============================================

                    barangays[
                        barangay_key
                    ]['puroks'][
                        purok
                    ] += 1

                    # =============================================
                    # YEAR COUNT
                    # =============================================

                    if year:

                        barangays[
                            barangay_key
                        ]['years'][
                            year
                        ] += 1

        except (
            OSError,
            csv.Error
        ) as e:

            print(
                f'Error reading '
                f'{dataset_path.name}: '
                f'{e}'
            )

    # Add only CHO-confirmed workflow cases to the live aggregate. Pending,
    # draft, and rejected reports must never alter official totals or maps.
    confirmed_web_cases = list(
        DengueCase.objects.filter(
            case_status='Confirmed',
            barangay__isnull=False,
        ).exclude(
            # These records are a database copy of the historical workbook
            # already included by the CSV loader above. Keep them in the
            # database for provenance, but do not count the same workbook
            # cases a second time in hotspot totals.
            user_account__username='dataset_importer',
            remarks__istartswith='Imported from workbook',
        ).select_related('barangay', 'purok')
    )
    for report in confirmed_web_cases:
        barangay = canonicalize_barangay(report.barangay.barangay_name)
        if not barangay:
            continue
        year = str(report.date_reported.year)
        purok = report.purok.purok_name if report.purok else 'Not specified'
        case_units = max(1, int(report.case_count or 1))
        barangay_key = normalize_name(barangay)
        all_years.add(year)
        total_dataset_cases += case_units
        if barangay_key not in barangays:
            barangays[barangay_key] = {
                'barangay': barangay,
                'city': 'Iligan City',
                'cases': 0,
                'puroks': Counter(),
                'years': Counter(),
            }
        barangays[barangay_key]['cases'] += case_units
        barangays[barangay_key]['puroks'][purok] += case_units
        barangays[barangay_key]['years'][year] += case_units

    # Do not silently render an arbitrary, empty future year as a historical
    # map. The selected value must exist in the loaded historical dataset.
    if selected_year.lower() != 'all' and selected_year not in all_years:
        selected_year = 'all'

    # =====================================================
    # FILTER BY YEAR
    # =====================================================

    if (
        selected_year
        and selected_year.lower() != 'all'
    ):

        filtered_barangays = {}

        for key, area in barangays.items():

            year_count = area[
                'years'
            ].get(
                selected_year,
                0
            )

            if year_count > 0:

                filtered_barangays[key] = {
                    'barangay':
                        area['barangay'],

                    'city':
                        area['city'],

                    'cases':
                        year_count,

                    'puroks':
                        Counter(),

                    'years':
                        area['years'],
                }

                # Only include puroks from selected year.
                #
                # Read datasets again to get the exact
                # selected-year purok counts.

        # Rebuild purok counts for selected year
        for dataset_path in dataset_files:

            try:

                with open(
                    dataset_path,
                    'r',
                    encoding='utf-8-sig',
                    newline=''
                ) as csvfile:

                    reader = csv.DictReader(
                        csvfile
                    )

                    for row in reader:

                        year = normalize_year(
                            row.get('Year')
                            or row.get('year')
                            or ''
                        )

                        if str(year) != str(
                            selected_year
                        ):
                            continue

                        city = (
                            row.get('(Current Address) City / Municipality')
                            or row.get('City')
                            or row.get('city')
                        )
                        if city is not None and not is_iligan_city(city):
                            continue

                        barangay_raw = (
                            row.get(
                                '(Current Address) Barangay'
                            )
                            or row.get('Barangay')
                            or row.get('barangay')
                            or ''
                        ).strip()
                        barangay = canonicalize_barangay(barangay_raw)
                        if not barangay:
                            continue

                        barangay_key = normalize_name(
                            barangay
                        )

                        if barangay_key not in filtered_barangays:
                            continue

                        purok = (
                            row.get(
                                '(Current Address) Sitio / Purok / Street Name'
                            )
                            or row.get('Purok')
                            or row.get('purok')
                            or row.get('Sitio')
                            or row.get('Street')
                            or ''
                        ).strip()

                        if not purok:
                            purok = 'Not specified'

                        filtered_barangays[
                            barangay_key
                        ]['puroks'][
                            purok
                        ] += 1

            except (
                OSError,
                csv.Error
            ) as e:

                print(
                    f'Error reading {dataset_path.name}: {e}'
                )

        # The CSV loop above only contains imported historical records. Add
        # confirmed web records for the selected year so popup purok counts
        # agree with the polygon's displayed case total.
        for report in confirmed_web_cases:
            if str(report.date_reported.year) != str(selected_year):
                continue
            barangay = canonicalize_barangay(report.barangay.barangay_name)
            if not barangay:
                continue
            barangay_key = normalize_name(barangay)
            if barangay_key not in filtered_barangays:
                continue
            purok = report.purok.purok_name if report.purok else 'Not specified'
            filtered_barangays[barangay_key]['puroks'][purok] += max(
                1,
                int(report.case_count or 1),
            )

        barangays = filtered_barangays

    # Include all official areas on every role's hotspot map, even when a
    # selected period has zero recorded cases.
    for official_name in ILIGAN_BARANGAYS:
        key = normalize_name(official_name)
        barangays.setdefault(key, {
            'barangay': official_name,
            'city': 'Iligan City',
            'cases': 0,
            'puroks': Counter(),
            'years': Counter(),
        })

    # =====================================================
    # CREATE HOTSPOT DATA
    # =====================================================

    hotspot_data = []

    for key, area in barangays.items():

        case_count = area[
            'cases'
        ]

        risk_level = get_risk(
            case_count
        )

        # =============================================
        # PUROK DATA
        # =============================================

        purok_data = []

        for purok_name, count in sorted(
            area['puroks'].items(),
            key=lambda item: (
                -item[1],
                item[0].lower()
            )
        ):

            purok_data.append({
                'name':
                    purok_name,

                'purok':
                    purok_name,

                'cases':
                    count,

                'case_count':
                    count,

                'risk_level':
                    get_risk(count),
            })

        named_puroks = [
            item for item in purok_data
            if item['name'].strip().casefold() not in {
                '', 'not specified', 'unknown', 'n/a', 'na', 'none', 'nan',
                'not available', 'not reported', 'unspecified',
            }
        ]
        top_purok = named_puroks[0] if named_puroks else None

        # =============================================
        # YEAR DATA
        # =============================================

        year_data = []

        for year, count in sorted(
            area['years'].items(),
            key=lambda item:
                str(item[0]),
            reverse=True
        ):

            year_data.append({
                'year':
                    str(year),

                'cases':
                    count,

                'case_count':
                    count,
            })

        # =============================================
        # BARANGAY DATA
        # =============================================

        hotspot_data.append({

            'barangay':
                area['barangay'],

            'city':
                area['city'],

            'cases':
                case_count,

            'case_count':
                case_count,

            'risk':
                risk_level,

            'risk_level':
                risk_level,

            'risk_color':
                get_risk_color(
                    risk_level
                ),

            'puroks':
                purok_data,

            'top_purok_name':
                top_purok['name'] if top_purok else 'No recorded purok',

            'top_purok_cases':
                top_purok['case_count'] if top_purok else 0,

            'years':
                year_data,

            'normalized_name':
                key,
        })

    # =====================================================
    # SORT
    # =====================================================

    hotspot_data.sort(
        key=lambda item:
            item['case_count'],
        reverse=True
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    total_cases = sum(
        item['case_count']
        for item in hotspot_data
    )

    monitored_barangays = len(
        hotspot_data
    )

    # This is intentionally separate from the number of barangays shown on
    # the historical map. A barangay is BHW-covered only when an approved
    # BHW account has been assigned to it by the CHO.
    assigned_bhws = UserAccount.objects.filter(
        role='BHW',
        account_status='APPROVED',
        assigned_barangay__isnull=False,
    )

    bhw_covered_barangays = assigned_bhws.values(
        'assigned_barangay_id'
    ).distinct().count()

    assigned_bhw_workers = assigned_bhws.count()

    high_risk_areas = sum(
        1
        for item in hotspot_data
        if item['risk_level']
        in [
            'High',
            'Critical'
        ]
    )

    critical_areas = sum(
        1
        for item in hotspot_data
        if item['risk_level']
        == 'Critical'
    )

    predicted_hotspots = sum(
        1
        for item in hotspot_data
        if item['risk_level']
        in [
            'High',
            'Critical'
        ]
    )

    # =====================================================
    # MAP DATA
    # =====================================================

    map_data = []

    for item in hotspot_data:

        map_data.append({

            'barangay':
                item['barangay'],

            'city':
                item['city'],

            'case_count':
                item['case_count'],

            'risk_level':
                item['risk_level'],

            'risk_color':
                item['risk_color'],

            'puroks':
                item['puroks'],

            'years':
                item['years'],

            # A boundary service may use a display label that differs from
            # the official dataset label. PSA calls the Saray polygon
            # "Saray-Tibanga" and supplies a separate Tibanga polygon.
            'boundary_names': (
                ['Saray', 'Saray-Tibanga']
                if item['barangay'] == 'Saray'
                else [item['barangay']]
            ),
        })

    # =====================================================
    # CONTEXT
    # =====================================================

    ordered_years = sorted(all_years, reverse=True)
    chronological_years = sorted(all_years, key=lambda value: int(value))
    historical_case_period = (
        f'{chronological_years[0]}–{chronological_years[-1]}'
        if len(chronological_years) > 1 else (chronological_years[0] if chronological_years else 'No historical records')
    )
    selected_year_label = (
        'All available historical years'
        if selected_year.lower() == 'all' else f'Historical year {selected_year}'
    )

    current_month = timezone.localdate().replace(day=1)
    current_month_query = DengueCase.objects.filter(
        case_status='Confirmed',
        date_reported__year=current_month.year,
        date_reported__month=current_month.month,
        barangay__isnull=False,
    ).exclude(
        user_account__username='dataset_importer',
        remarks__istartswith='Imported from workbook',
    ).values(
        'barangay__barangay_name',
    ).annotate(
        case_total=Sum('case_count'),
        report_count=Count('pk'),
    ).order_by('-case_total', 'barangay__barangay_name')
    current_month_top_barangays = [
        {
            'barangay': row['barangay__barangay_name'],
            'case_count': row['case_total'] or 0,
            'report_count': row['report_count'],
        }
        for row in current_month_query
    ]
    current_month_case_total = sum(
        row['case_count'] for row in current_month_top_barangays
    )

    return {

        'hotspot_data':
            hotspot_data,

        'hotspots':
            hotspot_data,

        'top_hotspots':
            hotspot_data[:10],

        'total_cases':
            total_cases,

        'monitored_barangays':
            monitored_barangays,

        'total_barangays':
            monitored_barangays,

        'bhw_covered_barangays':
            bhw_covered_barangays,

        'assigned_bhw_workers':
            assigned_bhw_workers,

        'high_risk_areas':
            high_risk_areas,

        'high_critical':
            high_risk_areas,

        'critical_areas':
            critical_areas,

        'predicted_hotspots':
            predicted_hotspots,

        'years': ordered_years,

        'available_years': ordered_years,

        'selected_year':
            selected_year,

        'selected_risk':
            selected_risk,

        # Historical map metadata: never use the forecast period here.
        'map_data_source': 'Historical dengue case records',
        'historical_case_period': historical_case_period,
        'selected_year_label': selected_year_label,
        'current_month_label': current_month.strftime('%B %Y'),
        'current_month_case_total': current_month_case_total,
        'current_month_report_count': sum(
            row['report_count'] for row in current_month_top_barangays
        ),
        'current_month_top_barangays': current_month_top_barangays,
        'dataset_quality': _dataset_quality_summary(),

        'dataset_count':
            len(dataset_files),

        'map_locations_json':
            json.dumps(
                map_data,
                ensure_ascii=False
            ),

        'hotspot_data_json':
            json.dumps(
                hotspot_data,
                ensure_ascii=False
            ),
    }


# =========================================================
# CHW DASHBOARD
# CHW ONLY
# =========================================================

@role_required('CHW')
def chw_dashboard(request):

    return render(
        request,
        'chw_dashboard.html',
        {
            'total_cases': DengueCase.objects.filter(user_account=request.user).count(),
            'pending_cases': DengueCase.objects.filter(user_account=request.user, case_status='Pending').count(),
            'recent_cases': DengueCase.objects.filter(user_account=request.user).select_related('barangay', 'purok').order_by('-date_reported')[:5],
        }
    )


def _render_chw_case_reports(request, form_case=None, form_data=None, view_case=None):
    latest_submission = ReportAuditLog.objects.filter(
        dengue_case_id=OuterRef('pk'),
        action='SUBMITTED',
    ).order_by('-created_at', '-audit_id').values('created_at')[:1]
    reports = DengueCase.objects.filter(
        user_account=request.user,
    ).annotate(
        latest_submission_at=Subquery(latest_submission),
    ).select_related(
        'barangay', 'purok', 'reviewed_by',
    ).prefetch_related(
        'audit_logs__actor',
    ).order_by(
        '-latest_submission_at', '-date_reported', '-dengue_case_id',
    )
    form_values = {
        'patient_age': '', 'patient_birth_date': '', 'patient_sex': '', 'patient_blood_type': '',
        'date_reported': '', 'barangay_id': '', 'purok_id': '',
        'location_details': '', 'remarks': '',
    }
    if form_case:
        form_values.update({
            'patient_age': form_case.patient_age,
            'patient_birth_date': form_case.patient_birth_date.isoformat() if form_case.patient_birth_date else '',
            'patient_sex': form_case.patient_sex,
            'patient_blood_type': form_case.patient_blood_type,
            'date_reported': form_case.date_reported.isoformat(),
            'barangay_id': form_case.barangay_id or '',
            'purok_id': form_case.purok_id or '',
            'location_details': form_case.location_details,
            'remarks': form_case.remarks,
        })
    if form_data:
        form_values.update({key: form_data.get(key, value) for key, value in form_values.items()})
    return render(request, 'chw_case_reports.html', {
        'reports': reports,
        'barangays': Barangay.objects.order_by('barangay_name'),
        'puroks': Purok.objects.select_related('barangay').order_by('barangay__barangay_name', 'purok_name'),
        'form_case': form_case,
        'view_case': view_case,
        'form_values': form_values,
    })


def _save_chw_case(request, case=None):
    """Save a CHW draft or send a complete suspected case to CHO."""
    action = request.POST.get('action')
    if action not in {'draft', 'submit'}:
        return None, 'Choose whether to save a draft or send the report to CHO.'

    barangay = get_object_or_404(Barangay, pk=request.POST.get('barangay_id'))
    purok_id = request.POST.get('purok_id')
    purok = Purok.objects.filter(pk=purok_id, barangay=barangay).first() if purok_id else None
    if purok_id and purok is None:
        return None, 'Choose a purok that belongs to the selected barangay.'

    try:
        patient_age = int(request.POST.get('patient_age', ''))
        reported_on = date.fromisoformat(request.POST.get('date_reported', ''))
    except (TypeError, ValueError):
        return None, 'Enter a valid patient age and report date.'
    birth_date_raw = request.POST.get('patient_birth_date', '').strip()
    try:
        patient_birth_date = date.fromisoformat(birth_date_raw) if birth_date_raw else None
    except ValueError:
        return None, 'Enter a valid patient birthdate.'
    if patient_birth_date and patient_birth_date > reported_on:
        return None, 'Patient birthdate cannot be after the report date.'
    if patient_age < 0 or patient_age > 130:
        return None, 'Patient age must be between 0 and 130.'

    patient_sex = request.POST.get('patient_sex', '').strip()
    location_details = request.POST.get('location_details', '').strip()
    if not patient_sex:
        return None, 'Select the patient sex.'
    if action == 'submit' and not location_details:
        return None, 'Exact location details are required before sending to CHO.'

    is_new = case is None
    report = case or DengueCase(user_account=request.user)
    report.barangay = barangay
    report.purok = purok
    report.patient_age = patient_age
    report.patient_birth_date = patient_birth_date
    report.patient_sex = patient_sex[:20]
    report.patient_blood_type = request.POST.get('patient_blood_type', '').strip().upper()[:5]
    report.date_reported = reported_on
    report.location_details = location_details
    report.remarks = request.POST.get('remarks', '').strip()
    report.case_status = 'Pending' if action == 'submit' else 'Draft'
    report.reviewed_by = None
    report.reviewed_at = None
    report.cho_review_note = ''
    report.save()
    audit_action = 'CREATED' if is_new else 'EDITED'
    if action == 'submit':
        audit_action = 'SUBMITTED'
    log_report_action(
        actor=request.user,
        dengue_case=report,
        action=audit_action,
        details='CHW submitted the suspected case to CHO.' if action == 'submit' else 'CHW saved a suspected-case draft.',
    )
    if action == 'submit':
        from .admin_notifications import notify_cho_admins
        notify_cho_admins(
            title='New suspected case report',
            message=f'{request.user.get_full_name() or request.user.username} submitted a suspected dengue case for CHO review in {barangay.barangay_name}.',
            link='/cho/suspected-cases/', actor=request.user, notification_type='CASE',
        )
    return report, None


@role_required('CHW')
def chw_case_reports(request):
    if request.method == 'POST':
        report, error = _save_chw_case(request)
        if error:
            messages.error(request, error)
            return _render_chw_case_reports(request, form_data=request.POST)
        if report.case_status == 'Pending':
            messages.success(request, 'Suspected case validated and sent to CHO for final verification.')
        else:
            messages.success(request, 'Suspected case saved as a draft. Review it before sending to CHO.')
        return redirect('chw_case_reports')

    editing_case = None
    edit_id = request.GET.get('edit')
    if edit_id:
        editing_case = get_object_or_404(
            DengueCase,
            pk=edit_id,
            user_account=request.user,
            case_status__in=['Draft', 'Pending', 'Rejected'],
        )
    view_case = None
    view_id = request.GET.get('view')
    if view_id:
        view_case = get_object_or_404(DengueCase, pk=view_id, user_account=request.user)
    return _render_chw_case_reports(request, form_case=editing_case, view_case=view_case)


@role_required('CHW')
def update_chw_case_report(request, case_id):
    if request.method != 'POST':
        return redirect('chw_case_reports')
    report = get_object_or_404(
        DengueCase,
        pk=case_id,
        user_account=request.user,
        case_status__in=['Draft', 'Pending', 'Rejected'],
    )
    saved, error = _save_chw_case(request, case=report)
    if error:
        messages.error(request, error)
        return _render_chw_case_reports(request, form_case=report, form_data=request.POST)
    if saved.case_status == 'Pending':
        messages.success(request, 'Suspected case validated and sent to CHO for final verification.')
    else:
        messages.success(request, 'Draft updated.')
    return redirect('chw_case_reports')


@role_required('CHW')
@require_POST
def delete_chw_case_report(request, case_id):
    """Allow a CHW to withdraw their own draft or report still awaiting CHO review."""
    with transaction.atomic():
        report = get_object_or_404(
            DengueCase.objects.select_for_update(),
            pk=case_id,
            user_account=request.user,
            case_status__in=['Draft', 'Pending'],
        )
        report_id = report.dengue_case_id
        previous_status = report.case_status

        # Keep the append-only history even though the report itself is removed.
        ReportAuditLog.objects.filter(dengue_case=report).update(dengue_case=None)
        log_report_action(
            actor=request.user,
            action='DELETED',
            details=(
                f'CHW deleted suspected case #{report_id} while it was {previous_status}. '
                'Earlier audit events were retained.'
            ),
        )
        report.delete()

    if previous_status == 'Pending':
        from .admin_notifications import notify_cho_admins
        notify_cho_admins(
            title='Suspected case report withdrawn',
            message=f'{request.user.get_full_name() or request.user.username} withdrew suspected case #{report_id} before CHO review.',
            link='/cho/suspected-cases/', actor=request.user, notification_type='CASE',
        )
    messages.success(request, f'Suspected case report #{report_id} was deleted.')
    return redirect('chw_case_reports')


@role_required('CHO')
def cho_suspected_case_reviews(request):
    chw_reports = DengueCase.objects.filter(user_account__role='CHW')
    pending_reports = chw_reports.filter(
        case_status='Pending',
    )
    search = request.GET.get('search', '').strip()
    if search:
        filters = (
            Q(user_account__first_name__icontains=search)
            | Q(user_account__last_name__icontains=search)
            | Q(user_account__username__icontains=search)
            | Q(barangay__barangay_name__icontains=search)
            | Q(purok__purok_name__icontains=search)
            | Q(location_details__icontains=search)
        )
        if search.isdigit():
            filters |= Q(dengue_case_id=int(search))
        pending_reports = pending_reports.filter(filters)

    reports = pending_reports.select_related(
        'user_account', 'barangay', 'purok'
    ).prefetch_related('audit_logs__actor').order_by(
        'date_reported', 'dengue_case_id'
    )
    reports_page = Paginator(reports, 15).get_page(request.GET.get('page'))
    modal_reports = chw_reports.select_related(
        'user_account', 'barangay', 'purok'
    ).order_by('-date_reported', '-dengue_case_id')
    return render(request, 'cho_suspected_case_reviews.html', {
        'reports': reports_page,
        'reports_page': reports_page,
        'search': search,
        'pending_count': chw_reports.filter(case_status='Pending').count(),
        'confirmed_count': chw_reports.filter(case_status='Confirmed').count(),
        'rejected_count': chw_reports.filter(case_status='Rejected').count(),
        'total_count': chw_reports.count(),
        'filtered_count': pending_reports.count(),
        'modal_pending_reports': modal_reports.filter(case_status='Pending'),
        'modal_confirmed_reports': modal_reports.filter(case_status='Confirmed'),
        'modal_rejected_reports': modal_reports.filter(case_status='Rejected'),
    })


@role_required('CHO')
def review_chw_case_report(request, case_id):
    if request.method != 'POST':
        return redirect('cho_suspected_case_reviews')
    report = get_object_or_404(DengueCase, pk=case_id, user_account__role='CHW', case_status='Pending')
    decision = request.POST.get('decision')
    if decision not in {'Confirmed', 'Rejected'}:
        messages.error(request, 'Choose Confirmed or Rejected.')
        return redirect('cho_suspected_case_reviews')
    note = f'CHO {decision.lower()} the suspected case after review.'
    report.case_status = decision
    report.cho_review_note = note
    report.reviewed_by = request.user
    report.reviewed_at = timezone.now()
    report.save(update_fields=['case_status', 'cho_review_note', 'reviewed_by', 'reviewed_at'])
    log_report_action(
        actor=request.user,
        dengue_case=report,
        action='VERIFIED' if decision == 'Confirmed' else 'REJECTED',
        details=note,
    )
    notify_user(
        report.user_account,
        'CASE',
        f'Suspected case #{report.dengue_case_id} {decision.lower()}',
        f'CHO review: {note}',
        created_by=request.user,
        link='/chw/suspected-cases/',
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'Suspected case #{report.dengue_case_id} {decision.lower()}',
        message=f'{request.user.get_full_name() or request.user.username} {decision.lower()} a CHW-submitted suspected case.',
        link='/cho/suspected-cases/', actor=request.user, notification_type='CASE',
    )
    if decision == 'Confirmed':
        messages.success(
            request,
            f'Suspected case #{report.dengue_case_id} was confirmed by CHO and is now included in live dashboard and hotspot-map totals.'
        )
    else:
        messages.success(request, f'Suspected case #{report.dengue_case_id} was rejected by CHO.')
    return redirect('cho_suspected_case_reviews')


# =========================================================
# BHW DASHBOARD
# BHW ONLY
# =========================================================

@role_required('BHW')
def bhw_dashboard(request):

    """
    Barangay Health Worker dashboard.

    BHW access is limited to the assigned barangay.
    Hotspot information uses the same calculations as
    the CHO/LGU hotspot map.
    """

    # =====================================================
    # HELPERS
    # =====================================================

    def assignment_name(
        value,
        possible_fields
    ):

        if not value:

            return ''

        for field_name in possible_fields:

            field_value = getattr(
                value,
                field_name,
                None
            )

            if field_value:

                return str(
                    field_value
                ).strip()

        return str(
            value
        ).strip()


    def normalize(value):

        return re.sub(
            r'\s+',
            ' ',
            str(
                value or ''
            ).strip().lower()
        )


    # =====================================================
    # ASSIGNED BARANGAY
    # =====================================================

    assigned_barangay_object = getattr(
        request.user,
        'assigned_barangay',
        None
    )


    if not assigned_barangay_object:

        assigned_barangay_object = getattr(
            request.user,
            'barangay',
            None
        )


    assigned_barangay = assignment_name(
        assigned_barangay_object,
        [
            'barangay_name',
            'name',
        ]
    )


    # =====================================================
    # ASSIGNED PUROK
    # =====================================================

    assigned_purok_object = getattr(
        request.user,
        'assigned_purok',
        None
    )


    if not assigned_purok_object:

        assigned_purok_object = getattr(
            request.user,
            'purok',
            None
        )


    assigned_purok = assignment_name(
        assigned_purok_object,
        [
            'purok_name',
            'name',
        ]
    )


    assignment_configured = bool(
        assigned_barangay
    )

    # The map's risk level is based on its selected/current map period. Keep
    # that separate from the all-period case history shown in the dashboard.
    area_case_records = _bhw_case_records(request.user)
    total_cases = sum(row['case_count'] for row in area_case_records)
    historical_case_records = sum(
        row['case_count'] for row in area_case_records if row['is_historical']
    )
    new_confirmed_case_records = sum(
        row['case_count'] for row in area_case_records if not row['is_historical']
    )


    # =====================================================
    # GET SAME HOTSPOT DATA AS CHO/LGU
    # =====================================================

    hotspot_context = build_hotspot_data(
        request
    )


    hotspot_data = hotspot_context.get(
        'hotspot_data',
        []
    )


    assigned_hotspot = None


    # =====================================================
    # FIND ASSIGNED BARANGAY
    # =====================================================

    if assigned_barangay:

        target_name = normalize(
            assigned_barangay
        )


        for area in hotspot_data:

            area_name = normalize(
                area.get(
                    'barangay',
                    ''
                )
            )


            if area_name == target_name:

                assigned_hotspot = area

                break


    # =====================================================
    # ASSIGNED AREA SUMMARY
    # =====================================================

    if assigned_hotspot:

        current_risk = (
            assigned_hotspot.get(
                'risk_level',
                'None'
            )
            or 'None'
        )


        assigned_purok_data = (
            assigned_hotspot.get(
                'puroks',
                []
            )
            or []
        )


    else:

        if assignment_configured:

            current_risk = 'None'

        else:

            current_risk = 'N/A'


        assigned_purok_data = []


    # =====================================================
    # NUMBER OF RECORDED PUROKS / LOCATIONS
    # =====================================================

    monitored_puroks = len(
        assigned_purok_data
    )


    # =====================================================
    # RESIDENT ENVIRONMENTAL REPORTS IN THIS BHW'S ASSIGNED AREA
    #
    # BHWs do not create, confirm, or reject dengue case records. They
    # verify resident environmental concerns in their assigned service area
    # and forward verified concerns to the CHO for the final decision.
    # =====================================================

    area_environmental_reports = _bhw_environmental_report_queryset(
        request.user
    ).select_related(
        'resident', 'barangay', 'purok', 'bhw_reviewed_by'
    )

    pending_environmental_reports = area_environmental_reports.filter(
        status='PENDING'
    ).count()

    forwarded_environmental_reports = area_environmental_reports.filter(
        status='FORWARDED'
    ).count()

    recent_environmental_reports = area_environmental_reports.order_by(
        '-submitted_at'
    )[:5]


    # =====================================================
    # CONTEXT
    # =====================================================

    context = {

        'assigned_barangay':
            assigned_barangay,

        'assigned_purok':
            assigned_purok,

        'assignment_configured':
            assignment_configured,

        'total_cases':
            total_cases,

        'historical_case_records': historical_case_records,

        'new_confirmed_case_records': new_confirmed_case_records,

        'pending_environmental_reports':
            pending_environmental_reports,

        'forwarded_environmental_reports':
            forwarded_environmental_reports,

        'current_risk':
            current_risk,

        'monitored_puroks':
            monitored_puroks,

        'assigned_purok_data':
            assigned_purok_data,

        'recent_environmental_reports':
            recent_environmental_reports,

        'assigned_hotspot':
            assigned_hotspot,

    }


    return render(
        request,
        'bhw_dashboard.html',
        context
    )

# =========================================================
# BHW HOTSPOT INFORMATION
# BHW ONLY
# =========================================================

@role_required('BHW')
def bhw_hotspot_information(request):

    assigned_barangay = request.user.assigned_barangay
    assigned_purok = request.user.assigned_purok

    # -----------------------------------------------------
    # DEFAULT VALUES
    # -----------------------------------------------------

    barangay_name = None
    total_cases = 0
    risk_level = 'N/A'
    historical_case_count = 0
    new_confirmed_case_count = 0

    location_data = []

    low_locations = 0
    moderate_locations = 0
    high_locations = 0
    critical_locations = 0

    # -----------------------------------------------------
    # ONLY PROCESS DATA WHEN BHW HAS ASSIGNMENT
    # -----------------------------------------------------

    if assigned_barangay:

        barangay_name = (
            assigned_barangay.barangay_name
        )

        # Load your historical dengue dataset
        dataset_cases = load_dengue_cases()

        # -------------------------------------------------
        # FILTER CASES TO ASSIGNED BARANGAY
        # -------------------------------------------------

        barangay_cases = []

        def normalize_area(value):
            return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()

        target_barangay = canonicalize_barangay(barangay_name)
        target_purok = normalize_area(assigned_purok.purok_name) if assigned_purok else ''

        for case in dataset_cases:
            if canonicalize_barangay(case.get('barangay')) != target_barangay:
                continue
            if target_purok and normalize_area(case.get('purok')) != target_purok:
                continue
            barangay_cases.append(case)

        historical_case_count = sum(
            1 for case in barangay_cases
            if case.get('source_file') != 'CHO-confirmed web record'
        )
        new_confirmed_case_count = sum(
            1 for case in barangay_cases
            if case.get('source_file') == 'CHO-confirmed web record'
        )

        total_cases = len(barangay_cases)

        # -------------------------------------------------
        # BARANGAY RISK CLASSIFICATION
        #
        # 0-5    = Low
        # 6-50   = Moderate
        # 51-100 = High
        # 101+   = Critical
        # -------------------------------------------------

        if total_cases <= 5:
            risk_level = 'Low'

        elif total_cases <= 50:
            risk_level = 'Moderate'

        elif total_cases <= 100:
            risk_level = 'High'

        else:
            risk_level = 'Critical'

        # -------------------------------------------------
        # GROUP BY PUROK / SITIO / STREET
        # -------------------------------------------------

        location_counts = {}

        for case in barangay_cases:

            location_name = str(
                case.get('purok', '')
            ).strip()

            if not location_name:
                location_name = 'Not specified'

            if location_name not in location_counts:
                location_counts[location_name] = 0

            location_counts[location_name] += 1

        # -------------------------------------------------
        # BUILD LOCATION DATA
        # -------------------------------------------------

        for location_name, case_count in location_counts.items():

            if case_count <= 5:
                location_risk = 'Low'
                low_locations += 1

            elif case_count <= 50:
                location_risk = 'Moderate'
                moderate_locations += 1

            elif case_count <= 100:
                location_risk = 'High'
                high_locations += 1

            else:
                location_risk = 'Critical'
                critical_locations += 1

            location_data.append({
                'name': location_name,
                'cases': case_count,
                'risk_level': location_risk,
            })

        # Highest case count first
        location_data.sort(
            key=lambda item: item['cases'],
            reverse=True
        )

    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    search = request.GET.get(
        'search',
        ''
    ).strip()

    selected_risk = request.GET.get(
        'risk',
        ''
    ).strip()

    if search:

        location_data = [
            item
            for item in location_data
            if search.lower() in item['name'].lower()
        ]

    if selected_risk:

        location_data = [
            item
            for item in location_data
            if (
                item['risk_level'].lower()
                == selected_risk.lower()
            )
        ]

    # -----------------------------------------------------
    # CONTEXT
    # -----------------------------------------------------

    context = {

        'assigned_barangay':
            assigned_barangay,

        'assigned_purok':
            assigned_purok,

        'assignment_configured':
            bool(assigned_barangay),

        'barangay_name':
            barangay_name,

        'total_cases':
            total_cases,

        'historical_case_count': historical_case_count,

        'new_confirmed_case_count': new_confirmed_case_count,

        'risk_level':
            risk_level,

        'location_data':
            location_data,

        'location_count':
            len(location_data),

        'low_locations':
            low_locations,

        'moderate_locations':
            moderate_locations,

        'high_locations':
            high_locations,

        'critical_locations':
            critical_locations,

        'search':
            search,

        'selected_risk':
            selected_risk,
    }

    return render(
        request,
        'bhw_hotspot_information.html',
        context
    )


# =========================================================
# LGU DASHBOARD
# LGU ONLY
# =========================================================

@role_required('LGU')
@require_GET
def lgu_dashboard(request):

    cases_data = load_dengue_cases()

    # -----------------------------------------------------
    # CITY-WIDE SUMMARY
    # -----------------------------------------------------

    total_cases = len(
        cases_data
    )

    barangays = set()

    years = set()

    for case in cases_data:

        barangay = str(
            case.get(
                'barangay',
                ''
            )
        ).strip()

        year = str(
            case.get(
                'year',
                ''
            )
        ).strip()

        if barangay:

            barangays.add(
                barangay
            )

        if year:

            years.add(
                year
            )

    context = {

        'total_cases':
            total_cases,

        'monitored_barangays':
            len(
                barangays
            ),

        'years':
            sorted(
                years,
                reverse=True
            ),

    }

    return render(
        request,
        'lgu_dashboard.html',
        context
    )

# =========================================================
# LGU PROFILE
# LGU ONLY
# =========================================================

@role_required('LGU')
def lgu_profile(request):

    """
    LGU Profile

    Allows an authenticated LGU user to:
    - View account information
    - Update first name
    - Update last name
    - Update email
    - Update contact number
    - Update office address

    Username and role cannot be changed here.
    """

    user = request.user


    # =====================================================
    # DEFAULT FORM DATA
    # =====================================================

    form_data = {
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'email': user.email or '',
        'contact_number': user.contact_number or '',
        'address': user.address or '',
    }


    # =====================================================
    # UPDATE PROFILE
    # =====================================================

    if request.method == 'POST':

        first_name = request.POST.get(
            'first_name',
            ''
        ).strip()

        last_name = request.POST.get(
            'last_name',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip()

        contact_number = request.POST.get(
            'contact_number',
            ''
        ).strip()

        address = request.POST.get(
            'address',
            ''
        ).strip()


        # =================================================
        # KEEP FORM DATA WHEN ERROR OCCURS
        # =================================================

        form_data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'contact_number': contact_number,
            'address': address,
        }


        # =================================================
        # REQUIRED FIELDS
        # =================================================

        if not first_name:

            messages.error(
                request,
                'First name is required.'
            )

            return render(
                request,
                'lgu_profile.html',
                {
                    'form_data': form_data
                }
            )


        if not last_name:

            messages.error(
                request,
                'Last name is required.'
            )

            return render(
                request,
                'lgu_profile.html',
                {
                    'form_data': form_data
                }
            )


        if not email:

            messages.error(
                request,
                'Email address is required.'
            )

            return render(
                request,
                'lgu_profile.html',
                {
                    'form_data': form_data
                }
            )


        # =================================================
        # CHECK EMAIL
        # =================================================

        email_exists = UserAccount.objects.filter(
            email__iexact=email
        ).exclude(
            pk=user.pk
        ).exists()


        if email_exists:

            messages.error(
                request,
                'This email address is already being used '
                'by another account.'
            )

            return render(
                request,
                'lgu_profile.html',
                {
                    'form_data': form_data
                }
            )


        # =================================================
        # UPDATE USER
        # =================================================

        user.first_name = first_name

        user.last_name = last_name

        user.email = email

        user.contact_number = contact_number

        user.address = address

        user.save(
            update_fields=[
                'first_name',
                'last_name',
                'email',
                'contact_number',
                'address',
            ]
        )


        # =================================================
        # SUCCESS
        # =================================================

        messages.success(
            request,
            'Your LGU profile has been updated successfully.'
        )

        return redirect(
            'lgu_profile'
        )


    # =====================================================
    # DISPLAY PROFILE
    # =====================================================

    return render(
        request,
        'lgu_profile.html',
        {
            'form_data': form_data
        }
    )

# =========================================================
# LGU RISK LEVELS
# LGU ONLY
# =========================================================

@role_required('LGU')
@require_GET
def lgu_risk_levels(request):

    """
    LGU read-only dengue risk level monitoring.

    Uses the SAME hotspot data and SAME risk classification
    as the CHO/LGU hotspot map.

    Risk thresholds:
        Low       = 1 - 5
        Moderate  = 6 - 50
        High      = 51 - 100
        Critical  = 101+
    """

    # =====================================================
    # GET SAME DATA USED BY HOTSPOT MAP
    # =====================================================

    context = build_hotspot_data(request)

    hotspot_data = context.get(
        'hotspot_data',
        []
    )


    # =====================================================
    # COUNT EACH RISK LEVEL
    # =====================================================

    low_count = sum(

        1

        for area in hotspot_data

        if area.get(
            'risk_level'
        ) == 'Low'

    )


    moderate_count = sum(

        1

        for area in hotspot_data

        if area.get(
            'risk_level'
        ) == 'Moderate'

    )


    high_count = sum(

        1

        for area in hotspot_data

        if area.get(
            'risk_level'
        ) == 'High'

    )


    critical_count = sum(

        1

        for area in hotspot_data

        if area.get(
            'risk_level'
        ) == 'Critical'

    )


    # =====================================================
    # HIGH + CRITICAL PRIORITY AREAS
    # =====================================================

    priority_areas = [

        area

        for area in hotspot_data

        if area.get(
            'risk_level'
        ) in [
            'High',
            'Critical'
        ]

    ]


    # =====================================================
    # CHART
    # =====================================================

    risk_chart_labels = [

        'Low',
        'Moderate',
        'High',
        'Critical',

    ]


    risk_chart_values = [

        low_count,
        moderate_count,
        high_count,
        critical_count,

    ]


    # =====================================================
    # ADD TO EXISTING HOTSPOT CONTEXT
    # =====================================================

    context.update({

        'low_count':
            low_count,

        'moderate_count':
            moderate_count,

        'high_count':
            high_count,

        'critical_count':
            critical_count,

        'priority_areas':
            priority_areas,

        'risk_chart_labels_json':
            json.dumps(
                risk_chart_labels
            ),

        'risk_chart_values_json':
            json.dumps(
                risk_chart_values
            ),

    })


    # =====================================================
    # RENDER
    # =====================================================

    return render(
        request,
        'lgu_risk_levels.html',
        context
    )


# =========================================================
# LGU CITY-WIDE MONITORING
# LGU ONLY
# =========================================================

# =========================================================
# LGU CITY-WIDE MONITORING
# LGU ONLY
# =========================================================

@role_required('LGU')
@require_GET
def city_wide_monitoring(request):

    """
    LGU City-Wide Dengue Monitoring

    Features:
    - Iligan City records only
    - Year filtering
    - Barangay case summary
    - Risk classification
    - Yearly dengue trend
    - Top barangays
    - Sex distribution
    - Age distribution
    - High/Critical risk monitoring
    """

    # =====================================================
    # LOAD DENGUE DATA
    # =====================================================

    cases_data = load_dengue_cases()


    # =====================================================
    # HELPER: NORMALIZE TEXT
    # =====================================================

    def normalize_text(value):

        return re.sub(
            r'\s+',
            ' ',
            str(value or '').strip().lower()
        )


    # =====================================================
    # HELPER: CHECK ILIGAN CITY
    # =====================================================

    def is_iligan_city(value):

        city = normalize_text(value)

        return city in {
            'city of iligan',
            'iligan city',
            'iligan',
        }


    # =====================================================
    # ONLY USE ILIGAN CITY RECORDS
    # =====================================================

    iligan_cases = [

        case

        for case in cases_data

        if is_iligan_city(
            case.get(
                'address',
                ''
            )
        )

    ]


    # =====================================================
    # AVAILABLE YEARS
    # =====================================================

    years = sorted(

        {

            str(
                case.get(
                    'year',
                    ''
                )
            ).strip()

            for case in iligan_cases

            if str(
                case.get(
                    'year',
                    ''
                )
            ).strip()

        },

        reverse=True

    )


    # =====================================================
    # YEAR FILTER
    # =====================================================

    selected_year = request.GET.get(
        'year',
        'all'
    ).strip()


    # Invalid year -> go back to all
    if (
        selected_year != 'all'
        and selected_year not in years
    ):

        selected_year = 'all'


    if selected_year == 'all':

        filtered_cases = iligan_cases

    else:

        filtered_cases = [

            case

            for case in iligan_cases

            if str(
                case.get(
                    'year',
                    ''
                )
            ).strip() == selected_year

        ]


    # =====================================================
    # DATASET COUNT
    # =====================================================

    dataset_dir = (
        Path(settings.BASE_DIR)
        / 'datasets'
    )


    # Report only the active CHO master file; archived and generated CSVs are
    # not additional case sources.
    dataset_count = int(
        (dataset_dir / 'WILBUR_DSO_dengue_2018_2026_authoritative.csv').is_file()
    )


    # =====================================================
    # RISK CLASSIFICATION
    #
    # SAME AS HOTSPOT MAP
    #
    # LOW       = 1 - 5
    # MODERATE  = 6 - 50
    # HIGH      = 51 - 100
    # CRITICAL  = 101+
    # =====================================================

    def get_risk(case_count):

        if case_count >= 101:

            return 'critical'

        elif case_count >= 51:

            return 'high'

        elif case_count >= 6:

            return 'moderate'

        elif case_count >= 1:

            return 'low'

        return 'none'


    # =====================================================
    # BARANGAY COUNTS
    # =====================================================

    barangay_counts = Counter()

    barangay_puroks = {}

    unassigned_location_cases = 0


    for case in filtered_cases:

        barangay = str(
            case.get(
                'barangay',
                ''
            )
        ).strip()


        purok = str(
            case.get(
                'purok',
                ''
            )
        ).strip()


        # =============================================
        # NO BARANGAY
        # =============================================

        if not barangay:

            unassigned_location_cases += 1

            continue


        # =============================================
        # COUNT BARANGAY CASE
        # =============================================

        barangay_counts[
            barangay
        ] += 1


        # =============================================
        # SAVE UNIQUE PUROK / SITIO / STREET
        # =============================================

        if barangay not in barangay_puroks:

            barangay_puroks[
                barangay
            ] = set()


        if purok:

            barangay_puroks[
                barangay
            ].add(
                purok
            )


    # =====================================================
    # BUILD BARANGAY LIST
    # =====================================================

    barangay_list = []


    for barangay, count in sorted(

        barangay_counts.items(),

        key=lambda item:
            item[1],

        reverse=True

    ):

        barangay_list.append({

            'barangay':
                barangay,

            'cases':
                count,

            'puroks':
                len(
                    barangay_puroks.get(
                        barangay,
                        set()
                    )
                ),

            'risk':
                get_risk(
                    count
                ),

        })


    # =====================================================
    # SUMMARY CARDS
    # =====================================================

    total_cases = len(
        filtered_cases
    )


    total_barangays = len(
        barangay_list
    )


    high_risk_barangays = [

        area

        for area in barangay_list

        if area[
            'risk'
        ] in {
            'high',
            'critical'
        }

    ]


    high_risk_count = len(
        high_risk_barangays
    )


    critical_count = sum(

        1

        for area in barangay_list

        if area[
            'risk'
        ] == 'critical'

    )


    # =====================================================
    # YEARLY DENGUE TREND
    #
    # Always uses all available Iligan City years.
    # =====================================================

    year_counts = Counter()


    for case in iligan_cases:

        year = str(
            case.get(
                'year',
                ''
            )
        ).strip()


        if year:

            year_counts[
                year
            ] += 1


    trend_years = sorted(
        year_counts.keys()
    )


    year_labels = trend_years


    year_values = [

        year_counts[
            year
        ]

        for year in trend_years

    ]


    # =====================================================
    # TOP 10 BARANGAYS
    # =====================================================

    top_barangays = barangay_list[:10]


    barangay_labels = [

        item[
            'barangay'
        ]

        for item in top_barangays

    ]


    barangay_values = [

        item[
            'cases'
        ]

        for item in top_barangays

    ]


    # =====================================================
    # RISK DISTRIBUTION
    # =====================================================

    risk_order = [

        'low',
        'moderate',
        'high',
        'critical',

    ]


    risk_counts = Counter(

        item[
            'risk'
        ]

        for item in barangay_list

    )


    risk_labels = [

        'Low',
        'Moderate',
        'High',
        'Critical',

    ]


    risk_values = [

        risk_counts[
            risk
        ]

        for risk in risk_order

    ]


    # =====================================================
    # SEX DISTRIBUTION
    # =====================================================

    sex_counts = Counter()


    for case in filtered_cases:

        sex = normalize_text(

            case.get(
                'sex',
                ''
            )

        )


        if sex == 'male':

            sex_counts[
                'Male'
            ] += 1


        elif sex == 'female':

            sex_counts[
                'Female'
            ] += 1


        else:

            sex_counts[
                'Not specified'
            ] += 1


    sex_labels = [

        label

        for label in [

            'Male',
            'Female',
            'Not specified',

        ]

        if sex_counts[
            label
        ] > 0

    ]


    sex_values = [

        sex_counts[
            label
        ]

        for label in sex_labels

    ]


    # =====================================================
    # AGE GROUP DISTRIBUTION
    # =====================================================

    age_counts = Counter({

        '0-4':
            0,

        '5-14':
            0,

        '15-24':
            0,

        '25-44':
            0,

        '45-64':
            0,

        '65+':
            0,

        'Not specified':
            0,

    })


    for case in filtered_cases:

        raw_age = str(
            case.get(
                'age',
                ''
            )
        ).strip()


        try:

            age = int(
                float(
                    raw_age
                )
            )


        except (
            TypeError,
            ValueError
        ):

            age_counts[
                'Not specified'
            ] += 1

            continue


        if age <= 4:

            age_counts[
                '0-4'
            ] += 1


        elif age <= 14:

            age_counts[
                '5-14'
            ] += 1


        elif age <= 24:

            age_counts[
                '15-24'
            ] += 1


        elif age <= 44:

            age_counts[
                '25-44'
            ] += 1


        elif age <= 64:

            age_counts[
                '45-64'
            ] += 1


        else:

            age_counts[
                '65+'
            ] += 1


    age_labels = [

        '0-4',
        '5-14',
        '15-24',
        '25-44',
        '45-64',
        '65+',

    ]


    if age_counts[
        'Not specified'
    ] > 0:

        age_labels.append(
            'Not specified'
        )


    age_values = [

        age_counts[
            label
        ]

        for label in age_labels

    ]


    # =====================================================
    # CONTEXT
    # =====================================================

    context = {

        # -------------------------
        # SUMMARY
        # -------------------------

        'total_cases':
            total_cases,

        'total_barangays':
            total_barangays,

        'high_risk_count':
            high_risk_count,

        'critical_count':
            critical_count,

        'dataset_count':
            dataset_count,


        # -------------------------
        # DATA QUALITY
        # -------------------------

        'unassigned_location_cases':
            unassigned_location_cases,


        # -------------------------
        # FILTER
        # -------------------------

        'years':
            years,

        'selected_year':
            selected_year,


        # -------------------------
        # BARANGAY DATA
        # -------------------------

        'barangay_list':
            barangay_list,

        'high_risk_barangays':
            high_risk_barangays,


        # -------------------------
        # YEAR CHART
        # -------------------------

        'year_labels_json':
            json.dumps(
                year_labels
            ),

        'year_values_json':
            json.dumps(
                year_values
            ),


        # -------------------------
        # BARANGAY CHART
        # -------------------------

        'barangay_labels_json':
            json.dumps(
                barangay_labels
            ),

        'barangay_values_json':
            json.dumps(
                barangay_values
            ),


        # -------------------------
        # RISK CHART
        # -------------------------

        'risk_labels_json':
            json.dumps(
                risk_labels
            ),

        'risk_values_json':
            json.dumps(
                risk_values
            ),


        # -------------------------
        # SEX CHART
        # -------------------------

        'sex_labels_json':
            json.dumps(
                sex_labels
            ),

        'sex_values_json':
            json.dumps(
                sex_values
            ),


        # -------------------------
        # AGE CHART
        # -------------------------

        'age_labels_json':
            json.dumps(
                age_labels
            ),

        'age_values_json':
            json.dumps(
                age_values
            ),

    }


    # =====================================================
    # RENDER PAGE
    # =====================================================

    return render(
        request,
        'city_wide_monitoring.html',
        context
    )


# =========================================================
# CHO PENDING USER REQUESTS
# CHO ONLY
# =========================================================

# =========================================================
# CHO PENDING REQUESTS
# CHO ONLY
# =========================================================

@role_required('CHO')
def pending_requests(request):

    pending_users = (
        UserAccount.objects
        .filter(
            account_status='PENDING'
        )
        .order_by('-date_joined')
    )

    context = {

        'pending_users':
            pending_users,

        'pending_count':
            pending_users.count(),

        'bhw_pending':
            pending_users.filter(
                role='BHW'
            ).count(),

        'chw_pending':
            pending_users.filter(
                role='CHW'
            ).count(),

        'lgu_pending':
            pending_users.filter(
                role='LGU'
            ).count(),
    }

    return render(
        request,
        'pending_requests.html',
        context
    )


# =========================================================
# NOTIFICATION CENTER
# =========================================================

@login_required(login_url='login')
def notification_center(request):
    visible_alert_ids = Alert.objects.filter(
        is_active=True,
        cho_review_confirmed=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).filter(
        Q(barangay__isnull=True) | Q(barangay_id=getattr(request.user, 'assigned_barangay_id', None))
    ).values_list('pk', flat=True)
    notification_query = SystemNotification.objects.filter(recipient=request.user).filter(
        ~Q(notification_type='ALERT')
        | Q(link__in=[f'/alert/{alert_id}' for alert_id in visible_alert_ids])
    ).order_by('-created_at', '-pk')
    if request.method == 'POST':
        notification_query.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        messages.success(request, 'Notifications marked as read.')
        return redirect('notification_center')
    total_count = notification_query.count()
    unread_count = notification_query.filter(is_read=False).count()
    read_count = total_count - unread_count
    search = request.GET.get('search', '').strip()
    filtered_notifications = notification_query
    if search:
        filtered_notifications = filtered_notifications.filter(
            Q(title__icontains=search)
            | Q(message__icontains=search)
            | Q(notification_type__icontains=search)
        )
    notifications_page = Paginator(filtered_notifications, 15).get_page(request.GET.get('page'))
    return render(request, 'notification_center.html', {
        'notifications': notifications_page,
        'notifications_page': notifications_page,
        'unread_count': unread_count,
        'read_count': read_count,
        'total_count': total_count,
        'filtered_count': filtered_notifications.count(),
        'search': search,
    })


# =========================================================
# CHO USER MANAGEMENT
# CHO ONLY
# =========================================================

@role_required('CHO')
def user_management(request):
    # Keep this screen scoped to resident accounts; staff administration has
    # separate workflows and must not appear in the resident list.
    resident_users = UserAccount.objects.filter(role='RESIDENT')
    search = request.GET.get('search', '').strip()
    if search:
        resident_users = resident_users.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(contact_number__icontains=search)
            | Q(address__icontains=search)
        )
    users = resident_users.order_by('-date_joined')
    users_page = Paginator(users, 50).get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    all_residents = UserAccount.objects.filter(role='RESIDENT')

    return render(
        request,
        'user_management.html',
        {
            'users': users_page,
            'users_page': users_page,
            'users_querystring': query_params.urlencode(),
            'filtered_resident_count': users_page.paginator.count,
            'resident_count': all_residents.count(),
            'resident_pending': all_residents.filter(account_status='PENDING').count(),
            'resident_approved': all_residents.filter(account_status='APPROVED').count(),
            'resident_verified': all_residents.filter(email_verified=True).count(),
            'search': search,
        }
    )


# =========================================================
# BHW AREA ASSIGNMENTS
# CHO ONLY
# =========================================================

@role_required('CHO')
def community_reports_review(request):
    """Final CHO queue for resident reports verified and forwarded by BHWs."""
    all_reports = CommunityReport.objects.select_related(
        'resident', 'barangay', 'purok', 'reviewed_by', 'bhw_reviewed_by'
    ).prefetch_related('audit_logs__actor')
    reports = all_reports.filter(status='FORWARDED').order_by('-bhw_reviewed_at', '-submitted_at')
    search = request.GET.get('search', '').strip()
    if search:
        reports = reports.filter(
            Q(observation_type__icontains=search)
            | Q(description__icontains=search)
            | Q(location_details__icontains=search)
            | Q(resident__first_name__icontains=search)
            | Q(resident__last_name__icontains=search)
            | Q(resident__username__icontains=search)
            | Q(barangay__barangay_name__icontains=search)
            | Q(purok__purok_name__icontains=search)
        )
    reports_page = Paginator(reports, 10).get_page(request.GET.get('page'))
    return render(request, 'community_reports_review.html', {
        'reports': reports_page,
        'reports_page': reports_page,
        'search': search,
        'filtered_count': reports.count(),
        'pending_count': all_reports.filter(status='FORWARDED').count(),
        'verified_count': all_reports.filter(status='VERIFIED').count(),
        'rejected_count': all_reports.filter(status='REJECTED').count(),
        'total_count': all_reports.count(),
    })


@role_required('CHO')
def review_community_report(request, report_id):
    if request.method != 'POST':
        return redirect('community_reports_review')

    report = get_object_or_404(CommunityReport, pk=report_id, status='FORWARDED')
    status = request.POST.get('status', '').upper()
    response = request.POST.get('staff_response', '').strip()
    if status not in {'VERIFIED', 'REJECTED'} or not response:
        messages.error(request, 'Choose Verified or Rejected and provide a response for the resident.')
        return redirect('community_reports_review')

    report.status = status
    report.staff_response = response
    report.reviewed_by = request.user
    report.reviewed_at = timezone.now()
    report.save(update_fields=['status', 'staff_response', 'reviewed_by', 'reviewed_at'])
    log_report_action(
        actor=request.user,
        community_report=report,
        action=status,
        details=response,
    )
    notify_user(
        report.resident,
        'REPLY',
        f'CHO replied to your {report.observation_type} report',
        response,
        created_by=request.user,
        link='/(tabs)/report',
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'Resident report {status.lower()}',
        message=f'{request.user.get_full_name() or request.user.username} {status.lower()} a {report.observation_type} report from {report.barangay.barangay_name}.',
        link='/cho/community-reports/', actor=request.user, notification_type='REPORT',
    )
    messages.success(request, 'Resident report reviewed and response saved.')
    return redirect('community_reports_review')


# =========================================================
# CHO ALERT AUTHORITY
# =========================================================

@role_required('CHO')
def alert_management(request):
    """Only explicitly CHO-reviewed alerts may be published to residents."""
    all_alerts = Alert.objects.select_related('barangay', 'created_by', 'cho_reviewed_by').order_by(
        '-is_active', '-created_at'
    )
    # Keep withdrawn alerts in storage for audit/history, but omit them from
    # the CHO's active alert list and its related summary counts.
    active_alerts = all_alerts.filter(is_active=True)
    alerts = active_alerts
    search = request.GET.get('search', '').strip()
    if search:
        alerts = alerts.filter(
            Q(title__icontains=search)
            | Q(message__icontains=search)
            | Q(barangay__barangay_name__icontains=search)
        )
    alerts_page = Paginator(alerts, 15).get_page(request.GET.get('page'))
    barangays = Barangay.objects.order_by('barangay_name')
    return render(request, 'alert_management.html', {
        'alerts': alerts_page,
        'alerts_page': alerts_page,
        'search': search,
        'filtered_count': alerts.count(),
        'total_count': active_alerts.count(),
        'active_count': active_alerts.count(),
        'pending_review_count': active_alerts.filter(cho_review_confirmed=False).count(),
        'reviewed_count': active_alerts.filter(cho_review_confirmed=True).count(),
        'barangays': barangays,
        'risk_choices': Alert.RISK_CHOICES,
    })


def _deliver_reviewed_alert(alert, actor):
    """Notify intended residents only after the CHO review has been saved."""
    recipients = UserAccount.objects.filter(
        role='RESIDENT', account_status='APPROVED',
    )
    if alert.barangay:
        recipients = recipients.filter(assigned_barangay=alert.barangay)
        target_area = alert.barangay.barangay_name
        audience = f'{target_area} residents'
    else:
        target_area = 'All Iligan City'
        audience = 'all Iligan City residents'
    email_sent = email_failed = email_missing = 0
    # Email should open the resident app's Alerts/Notifications tab, where the
    # published alert is already available as an in-app notification.
    mobile_link = settings.MOBILE_NOTIFICATIONS_LINK
    for resident in recipients.iterator():
        notification_link = f'/alert/{alert.pk}'
        existing_notification = SystemNotification.objects.filter(
            recipient=resident,
            notification_type='ALERT',
            link=notification_link,
        ).order_by('-created_at', '-notification_id').first()
        if existing_notification:
            # Republishing the same alert updates its existing inbox record
            # instead of adding another copy for the same resident.
            existing_notification.title = alert.title
            existing_notification.message = alert.message
            existing_notification.created_by = actor
            existing_notification.is_read = False
            existing_notification.read_at = None
            existing_notification.save(update_fields=[
                'title', 'message', 'created_by', 'is_read', 'read_at',
            ])
        else:
            notify_user(
                resident,
                'ALERT',
                alert.title,
                alert.message,
                created_by=actor,
                link=notification_link,
            )
        if resident.email and resident.email_verified:
            text_body = (
                f'{alert.title}\n\n'
                f'Target area: {target_area}\n'
                f'Risk level: {alert.get_risk_level_display()}\n\n'
                f'{alert.message}\n\n'
                f'Open DengueWatch Notifications: {mobile_link}\n\n'
                'If the app is not installed, open DengueWatch and check Alerts.'
            )
            html_body = (
                '<div style="font-family:Arial,sans-serif;line-height:1.6">'
                f'<h2>{escape(alert.title)}</h2>'
                f'<p><strong>Target area:</strong> {escape(target_area)}<br>'
                f'<strong>Risk level:</strong> {escape(alert.get_risk_level_display())}</p>'
                f'<p>{escape(alert.message).replace(chr(10), "<br>")}</p>'
                f'<p><a href="{escape(mobile_link)}" style="display:inline-block;padding:12px 18px;'
                'background:#0d6b57;color:#fff;text-decoration:none;border-radius:6px">'
                'Open DengueWatch Notifications</a></p>'
                '<p>If the button does not open the app, open DengueWatch Mobile and '
                'check Alerts.</p></div>'
            )
            try:
                email = EmailMultiAlternatives(
                    subject=f'DengueWatch alert: {alert.title}',
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL or None,
                    to=[resident.email],
                )
                email.attach_alternative(html_body, 'text/html')
                email_sent += email.send(fail_silently=False)
            except Exception:
                email_failed += 1
        else:
            email_missing += 1

    if settings.EMAIL_BACKEND.endswith('console.EmailBackend'):
        email_status = (
            f'{email_missing} resident(s) have unverified/missing email. Email is in console mode; '
            'configure Gmail SMTP to deliver it.'
        )
    else:
        email_status = (
            f'{email_sent} email(s) sent; {email_failed} failed; '
            f'{email_missing} resident(s) have an unverified or missing email.'
        )
    return audience, email_status


@role_required('CHO')
def create_alert(request):
    if request.method != 'POST':
        return redirect('alert_management')

    title = request.POST.get('title', '').strip()
    message = request.POST.get('message', '').strip()
    risk_level = request.POST.get('risk_level', '').upper()
    barangay_id = request.POST.get('barangay_id', '').strip()
    valid_levels = {value for value, _label in Alert.RISK_CHOICES}
    if not title or not message or risk_level not in valid_levels:
        messages.error(request, 'Provide an alert title, message, and valid risk level.')
        return redirect('alert_management')
    review_note = request.POST.get('cho_review_note', '').strip()
    if request.POST.get('cho_review_confirmed') != 'on' or len(review_note) < 20:
        messages.error(
            request,
            'Before publishing, confirm CHO review and provide a review note of at least 20 characters.',
        )
        return redirect('alert_management')

    barangay = None
    if barangay_id:
        barangay = get_object_or_404(Barangay, pk=barangay_id)
    alert = Alert.objects.create(
        title=title,
        message=message,
        risk_level=risk_level,
        barangay=barangay,
        created_by=request.user,
        cho_review_confirmed=True,
        cho_review_note=review_note,
        cho_reviewed_by=request.user,
        cho_reviewed_at=timezone.now(),
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'Resident alert published: {title}',
        message=f'{request.user.get_full_name() or request.user.username} published a {risk_level.lower()}-risk alert for {barangay.barangay_name if barangay else "All Iligan City"}.',
        link='/cho/alerts/', actor=request.user, notification_type='ALERT',
    )
    audience, email_status = _deliver_reviewed_alert(alert, request.user)
    messages.success(request, f'Alert published for {audience}. {email_status}')
    return redirect('alert_management')


@role_required('CHO')
def toggle_alert(request, alert_id):
    if request.method != 'POST':
        return redirect('alert_management')
    alert = get_object_or_404(Alert, pk=alert_id)
    if alert.is_active:
        alert.is_active = False
        alert.save(update_fields=['is_active'])
        from .admin_notifications import notify_cho_admins
        notify_cho_admins(
            title=f'Resident alert withdrawn: {alert.title}',
            message=f'{request.user.get_full_name() or request.user.username} withdrew a previously published resident alert.',
            link='/cho/alerts/', actor=request.user, notification_type='ALERT',
        )
        messages.success(request, 'Alert withdrawn.')
    else:
        review_note = request.POST.get('cho_review_note', '').strip()
        if request.POST.get('cho_review_confirmed') != 'on' or len(review_note) < 20:
            messages.error(
                request,
                'Before reactivating, confirm a fresh CHO review and provide a review note of at least 20 characters.',
            )
            return redirect('alert_management')
        alert.is_active = True
        alert.cho_review_confirmed = True
        alert.cho_review_note = review_note
        alert.cho_reviewed_by = request.user
        alert.cho_reviewed_at = timezone.now()
        alert.save(update_fields=[
            'is_active', 'cho_review_confirmed', 'cho_review_note',
            'cho_reviewed_by', 'cho_reviewed_at',
        ])
        from .admin_notifications import notify_cho_admins
        notify_cho_admins(
            title=f'Resident alert re-published: {alert.title}',
            message=f'{request.user.get_full_name() or request.user.username} re-reviewed and re-published a resident alert.',
            link='/cho/alerts/', actor=request.user, notification_type='ALERT',
        )
        audience, email_status = _deliver_reviewed_alert(alert, request.user)
        messages.success(request, f'Alert re-reviewed and published for {audience}. {email_status}')
    return redirect('alert_management')


def _bhw_environmental_report_queryset(user):
    """Return only reports inside the BHW's explicitly assigned service area."""
    assigned_barangay = getattr(user, 'assigned_barangay', None)
    if not assigned_barangay:
        return CommunityReport.objects.none()
    reports = CommunityReport.objects.filter(barangay=assigned_barangay)
    assigned_purok = getattr(user, 'assigned_purok', None)
    if assigned_purok:
        reports = reports.filter(purok=assigned_purok)
    return reports


@role_required('BHW')
def bhw_environmental_reports(request):
    reports = _bhw_environmental_report_queryset(request.user).select_related(
        'resident', 'barangay', 'purok', 'bhw_reviewed_by'
    ).prefetch_related('audit_logs__actor').filter(status__in=['PENDING', 'FORWARDED']).order_by('status', '-submitted_at')
    return render(request, 'bhw_environmental_reports.html', {
        'reports': reports,
        'assigned_barangay': request.user.assigned_barangay,
        'assigned_purok': request.user.assigned_purok,
        'pending_count': reports.filter(status='PENDING').count(),
        'forwarded_count': reports.filter(status='FORWARDED').count(),
        'total_count': reports.count(),
    })


@role_required('BHW')
def forward_environmental_report(request, report_id):
    if request.method != 'POST':
        return redirect('bhw_environmental_reports')
    report = get_object_or_404(
        _bhw_environmental_report_queryset(request.user),
        pk=report_id,
        status='PENDING',
    )
    note = request.POST.get('bhw_review_note', '').strip()
    if not note:
        messages.error(request, 'Provide a BHW verification note before forwarding the concern to CHO.')
        return redirect('bhw_environmental_reports')
    report.status = 'FORWARDED'
    report.bhw_review_note = note
    report.bhw_reviewed_by = request.user
    report.bhw_reviewed_at = timezone.now()
    report.save(update_fields=[
        'status', 'bhw_review_note', 'bhw_reviewed_by', 'bhw_reviewed_at',
    ])
    log_report_action(
        actor=request.user,
        community_report=report,
        action='FORWARDED',
        details=note,
    )
    notify_user(
        report.resident,
        'REPORT',
        f'Your {report.observation_type} report was verified by BHW',
        'Your concern was verified and forwarded to the City Health Office for final review.',
        created_by=request.user,
        link='/(tabs)/report',
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'BHW forwarded a {report.observation_type} concern',
        message=f'{report.barangay.barangay_name}: {note}',
        actor=request.user, link='/cho/community-reports/', notification_type='REPORT',
    )
    messages.success(request, 'Environmental concern verified and forwarded to CHO for final review.')
    return redirect('bhw_environmental_reports')


@role_required('CHO')
def bhw_assignments(request):
    """
    Allows the City Health Office to assign approved
    Barangay Health Workers to a Barangay and optional Purok.
    """

    # -----------------------------------------------------
    # APPROVED BHW ACCOUNTS
    # -----------------------------------------------------

    bhw_users = (
        UserAccount.objects
        .filter(
            role__in=['BHW', 'CHW'],
            account_status='APPROVED'
        )
        .select_related(
            'assigned_barangay',
            'assigned_purok'
        )
        .order_by(
            'first_name',
            'last_name',
            'username'
        )
    )

    # -----------------------------------------------------
    # BARANGAYS
    # -----------------------------------------------------

    barangays = (
        Barangay.objects
        .all()
        .order_by('barangay_name')
    )

    # -----------------------------------------------------
    # PUROKS
    # -----------------------------------------------------

    puroks = (
        Purok.objects
        .select_related('barangay')
        .all()
        .order_by(
            'barangay__barangay_name',
            'purok_name'
        )
    )

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    total_bhw = bhw_users.count()

    assigned_bhw = bhw_users.filter(
        assigned_barangay__isnull=False
    ).count()

    unassigned_bhw = bhw_users.filter(
        assigned_barangay__isnull=True
    ).count()

    barangay_count = barangays.count()

    # -----------------------------------------------------
    # CONTEXT
    # -----------------------------------------------------

    context = {
        'bhw_users': bhw_users,
        'barangays': barangays,
        'puroks': puroks,

        'total_bhw': total_bhw,
        'assigned_bhw': assigned_bhw,
        'unassigned_bhw': unassigned_bhw,
        'barangay_count': barangay_count,
    }

    return render(
        request,
        'bhw_assignments.html',
        context
    )


# =========================================================
# ASSIGN / UPDATE BHW AREA
# CHO ONLY
# =========================================================

@role_required('CHO')
def assign_bhw_area(request, user_id):
    """
    Assign or update the Barangay and optional Purok
    of an approved BHW account.
    """

    if request.method != 'POST':

        messages.error(
            request,
            'Invalid request method.'
        )

        return redirect(
            'bhw_assignments'
        )

    # -----------------------------------------------------
    # GET BHW
    # -----------------------------------------------------

    bhw = get_object_or_404(
        UserAccount,
        id=user_id,
        role__in=['BHW', 'CHW']
    )

    # -----------------------------------------------------
    # ONLY APPROVED BHW
    # -----------------------------------------------------

    if bhw.account_status != 'APPROVED':

        messages.error(
            request,
            'Only approved BHW accounts can be assigned '
            'to a monitoring area.'
        )

        return redirect(
            'bhw_assignments'
        )

    # -----------------------------------------------------
    # GET FORM VALUES
    # -----------------------------------------------------

    barangay_id = request.POST.get(
        'barangay',
        ''
    ).strip()

    purok_id = request.POST.get(
        'purok',
        ''
    ).strip()

    # -----------------------------------------------------
    # BARANGAY REQUIRED
    # -----------------------------------------------------

    if not barangay_id:

        messages.error(
            request,
            'Please select a Barangay.'
        )

        return redirect(
            'bhw_assignments'
        )

    # -----------------------------------------------------
    # GET BARANGAY
    # -----------------------------------------------------

    barangay = get_object_or_404(
        Barangay,
        barangay_id=barangay_id
    )

    # -----------------------------------------------------
    # GET PUROK
    # -----------------------------------------------------

    purok = None

    if purok_id:

        try:

            purok = Purok.objects.get(
                purok_id=purok_id,
                barangay=barangay
            )

        except Purok.DoesNotExist:

            messages.error(
                request,
                'The selected Purok does not belong '
                'to the selected Barangay.'
            )

            return redirect(
                'bhw_assignments'
            )

    # -----------------------------------------------------
    # SAVE ASSIGNMENT
    # -----------------------------------------------------

    bhw.assigned_barangay = barangay
    bhw.assigned_purok = purok

    bhw.save(
        update_fields=[
            'assigned_barangay',
            'assigned_purok',
        ]
    )

    assigned_area = barangay.barangay_name
    if purok:
        assigned_area = f'{assigned_area} — {purok.purok_name}'
    notify_user(
        bhw,
        'ASSIGNMENT',
        'New monitoring-area assignment',
        f'CHO assigned you to {assigned_area}.',
        created_by=request.user,
        link='/dashboard/',
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'Monitoring area assigned: {bhw.username}',
        message=f'{request.user.get_full_name() or request.user.username} assigned {bhw.username} to {assigned_area}.',
        actor=request.user, link='/cho/bhw-assignments/', notification_type='ASSIGNMENT',
    )

    # -----------------------------------------------------
    # SUCCESS MESSAGE
    # -----------------------------------------------------

    if purok:

        messages.success(
            request,
            f'{bhw.username} was assigned to '
            f'{barangay.barangay_name} - '
            f'{purok.purok_name}.'
        )

    else:

        messages.success(
            request,
            f'{bhw.username} was assigned to '
            f'{barangay.barangay_name} '
            f'for barangay-wide monitoring.'
        )

    return redirect(
        'bhw_assignments'
    )


# =========================================================
# REMOVE BHW AREA ASSIGNMENT
# CHO ONLY
# =========================================================

@role_required('CHO')
def remove_bhw_assignment(request, user_id):
    """
    Remove the Barangay and Purok assignment
    from a BHW account.
    """

    if request.method != 'POST':

        messages.error(
            request,
            'Invalid request method.'
        )

        return redirect(
            'bhw_assignments'
        )

    # -----------------------------------------------------
    # GET BHW
    # -----------------------------------------------------

    bhw = get_object_or_404(
        UserAccount,
        id=user_id,
        role__in=['BHW', 'CHW']
    )

    # -----------------------------------------------------
    # REMOVE ASSIGNMENT
    # -----------------------------------------------------

    bhw.assigned_barangay = None
    bhw.assigned_purok = None

    bhw.save(
        update_fields=[
            'assigned_barangay',
            'assigned_purok',
        ]
    )

    notify_user(
        bhw,
        'ASSIGNMENT',
        'Monitoring-area assignment removed',
        'CHO removed your assigned barangay/purok monitoring area.',
        created_by=request.user,
        link='/dashboard/',
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'Monitoring area removed: {bhw.username}',
        message=f'{request.user.get_full_name() or request.user.username} removed {bhw.username}’s barangay/purok assignment.',
        actor=request.user, link='/cho/bhw-assignments/', notification_type='ASSIGNMENT',
    )

    messages.success(
        request,
        f'Area assignment for {bhw.username} '
        f'has been removed.'
    )

    return redirect(
        'bhw_assignments'
    )

# =========================================================
# APPROVE USER
# CHO ONLY
# =========================================================

@role_required('CHO')
@require_POST
def approve_user(request, user_id):

    user = get_object_or_404(
        UserAccount,
        id=user_id,
        role__in=['CHO', 'BHW', 'CHW', 'LGU', 'RESIDENT'],
        account_status='PENDING',
    )

    if not user.email_verified:
        messages.error(request, f'{user.username} must verify their email before approval. Ask them to use the resend verification link.')
        return redirect('pending_requests' if request.POST.get('next') == 'pending_requests' else 'user_management')

    user.account_status = 'APPROVED'
    user.is_active = True

    user.save(
        update_fields=[
            'account_status',
            'is_active',
        ]
    )

    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'Account approved: {user.username}',
        message=f'{request.user.get_full_name() or request.user.username} approved a {user.get_role_display()} account.',
        actor=request.user, link='/pending-requests/', notification_type='ADMIN',
    )
    notify_user(user, 'ADMIN', 'DengueWatch account approved', 'Your account has been approved. You can now sign in.', created_by=request.user, link='/login/')

    # -----------------------------------------------------
    # SPECIAL MESSAGE FOR BHW
    # -----------------------------------------------------

    if user.role == 'BHW':

        messages.success(
            request,
            f'{user.username} has been approved. '
            f'You can now assign this BHW to a Barangay '
            f'under BHW Assignments.'
        )

    else:

        messages.success(
            request,
            f'{user.username} has been approved.'
        )

    return redirect(
        'pending_requests' if request.POST.get('next') == 'pending_requests' else 'user_management'
    )

# =========================================================
# REJECT USER
# CHO ONLY
# =========================================================

@role_required('CHO')
@require_POST
def reject_user(
    request,
    user_id
):

    try:

        user = UserAccount.objects.get(
            id=user_id,
            role__in=['CHO', 'BHW', 'CHW', 'LGU', 'RESIDENT'],
            account_status='PENDING',
        )

        user.account_status = 'REJECTED'

        user.is_active = False

        user.save()

        from .admin_notifications import notify_cho_admins
        notify_cho_admins(
            title=f'Account rejected: {user.username}',
            message=f'{request.user.get_full_name() or request.user.username} rejected a {user.get_role_display()} account request.',
            actor=request.user, link='/pending-requests/', notification_type='ADMIN',
        )

        messages.success(
            request,
            f'{user.username} has been rejected.'
        )

    except UserAccount.DoesNotExist:

        messages.error(
            request,
            'User account not found.'
        )

    return redirect(
        'pending_requests' if request.POST.get('next') == 'pending_requests' else 'user_management'
    )


# =========================================================
# PROFILE
# =========================================================

@login_required(login_url='login')
def profile(request):

    user = request.user

    if request.method == 'POST':

        first_name = request.POST.get(
            'first_name',
            ''
        ).strip()

        middle_name = request.POST.get(
            'middle_name',
            ''
        ).strip()

        last_name = request.POST.get(
            'last_name',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip()

        contact_number = request.POST.get(
            'contact_number',
            ''
        ).strip()

        address = request.POST.get(
            'address',
            ''
        ).strip()

        profile_picture = request.FILES.get(
            'profile_picture'
        )

        # =========================================
        # CLEAR PROFILE PICTURE
        # =========================================

        if request.POST.get("clear_profile_picture") == "1":

            if user.profile_picture:

                user.profile_picture.delete(
                    save=False
                )

                user.profile_picture = None

                user.save(
                    update_fields=["profile_picture"]
                )

            messages.success(
                request,
                "Profile picture has been cleared."
            )

            return redirect("profile")


        # ---------------------------------------------
        # UPDATE PERSONAL INFORMATION
        # ---------------------------------------------

        user.first_name = first_name

        user.middle_name = middle_name

        user.last_name = last_name

        user.email = email

        user.contact_number = contact_number

        user.address = address

        # ---------------------------------------------
        # UPDATE PROFILE PICTURE
        # ---------------------------------------------

        if profile_picture:

            user.profile_picture = profile_picture

        user.save()

        messages.success(
            request,
            'Your profile has been successfully updated.'
        )

        return redirect('profile')

    context = {
        'user': user,
    }

    return render(
        request,
        'profile.html',
        context
    )

# =========================================================
# LOGOUT
# =========================================================

@login_required(login_url='login')
def logout_view(request):

    logout(request)

    messages.success(
        request,
        'You have successfully logged out.'
    )

    return redirect(
        'login'
    )
