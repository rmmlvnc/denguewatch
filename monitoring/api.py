import csv
import json
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from django.contrib.auth import authenticate
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from PIL import Image

from .models import (
    Alert,
    Barangay,
    CommunityReport,
    DengueCase,
    HotspotPrediction,
    MobileAccessToken,
    Purok,
    SystemNotification,
    UserAccount,
    notify_user,
    log_report_action,
)
from .ml.service import BLOOD_TYPE_FEATURE_NOTICE, prediction_context
from .ml.definition import PREDICTION_DEFINITION
from .locations import ILIGAN_BARANGAYS, canonicalize_barangay
from .views import build_hotspot_data


def _body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None


def _error(message, status=400, fields=None):
    data = {"success": False, "message": message}
    if fields:
        data["errors"] = fields
    return JsonResponse(data, status=status)


def _map_key(value):
    """Match display labels to the official boundary GeoJSON labels."""
    return " ".join(str(value or "").lower().replace("-", " ").replace(".", " ").split())


def _official_barangay_centers():
    """Return one display coordinate per official barangay boundary.

    Historical case records do not contain coordinates. Deriving these points
    from the bundled boundary geometry keeps the resident hotspot map visible
    without inventing a location or using an external map service.
    """
    boundary_path = Path(settings.BASE_DIR) / "static" / "data" / "iligan_barangays.geojson"
    try:
        features = json.loads(boundary_path.read_text(encoding="utf-8")).get("features", [])
    except (OSError, json.JSONDecodeError):
        return {}

    def pairs(value):
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            return [(float(value[0]), float(value[1]))]
        if isinstance(value, list):
            return [pair for child in value for pair in pairs(child)]
        return []

    centers = {}
    for feature in features:
        name = feature.get("properties", {}).get("brgy_name")
        coordinates = pairs(feature.get("geometry", {}).get("coordinates", []))
        if name and coordinates:
            longitude = sum(pair[0] for pair in coordinates) / len(coordinates)
            latitude = sum(pair[1] for pair in coordinates) / len(coordinates)
            centers[_map_key(name)] = (latitude, longitude)
    return centers


def _historical_map_item(index, item, centers):
    latitude, longitude = centers.get(_map_key(item["barangay"]), (None, None))
    return {
        "id": index,
        "barangay_id": None,
        "barangay": item["barangay"],
        "current_cases": item["case_count"],
        "predicted_cases": item["case_count"],
        "risk_level": item["risk_level"],
        "trend": "Historical case total",
        "latitude": latitude,
        "longitude": longitude,
    }


def _user_data(user):
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "contact_number": user.contact_number,
        "address": user.address,
        "profile_picture": user.profile_picture.url if user.profile_picture else None,
        "role": user.role,
        "account_status": user.account_status,
        "email_verified": user.email_verified,
        "barangay": (
            {"id": user.assigned_barangay_id, "name": user.assigned_barangay.barangay_name}
            if user.assigned_barangay_id else None
        ),
    }


def mobile_auth(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        raw_token = header[7:].strip() if header.startswith("Bearer ") else ""
        user = MobileAccessToken.authenticate(raw_token)
        if not user:
            return _error("Valid mobile access token is required.", status=401)
        request.mobile_user = user
        request.mobile_raw_token = raw_token
        return view(request, *args, **kwargs)

    return wrapped


@require_http_methods(["GET"])
def health(request):
    return JsonResponse({"success": True, "service": "DengueWatch Mobile API", "version": "1.0"})


@csrf_exempt
@require_http_methods(["POST"])
def register_resident(request):
    data = _body(request)
    if data is None:
        return _error("Invalid JSON body.")

    required = ["first_name", "last_name", "email", "password"]
    missing = {name: "This field is required." for name in required if not str(data.get(name, "")).strip()}
    # Mobile may use its bundled official barangay list before the locations
    # endpoint is reachable. In that case the canonical barangay name is the
    # stable identifier; a database-specific primary key is not required.
    if not data.get("barangay_id") and not str(data.get("barangay_name", "")).strip():
        missing["barangay"] = "Please select a barangay."
    if missing:
        return _error("Please complete the required fields.", fields=missing)
    if len(data["password"]) < 8:
        return _error("Password must contain at least 8 characters.", fields={"password": "Too short."})

    barangay = Barangay.objects.filter(pk=data.get("barangay_id")).first()
    if not barangay:
        barangay_name = canonicalize_barangay(data.get("barangay_name", ""))
        barangay = Barangay.objects.filter(barangay_name=barangay_name).first()
    if not barangay:
        return _error("Selected barangay was not found.", fields={"barangay_id": "Invalid barangay."})
    purok = None
    if data.get("purok_id"):
        purok = Purok.objects.filter(pk=data["purok_id"], barangay=barangay).first()
        if not purok:
            return _error("Selected purok does not belong to the barangay.")

    email = data["email"].strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return _error("Enter a valid email address.", fields={"email": "Invalid email address."})
    username = email
    try:
        user = UserAccount.objects.create_user(
            username=username,
            email=email,
            password=data["password"],
            first_name=data["first_name"].strip(),
            last_name=data["last_name"].strip(),
            contact_number=str(data.get("contact_number", "")).strip(),
            address=str(data.get("address", "")).strip(),
            role="RESIDENT",
            account_status="APPROVED",
            assigned_barangay=barangay,
            assigned_purok=purok,
        )
    except IntegrityError:
        return _error("An account with this email already exists.", status=409)

    verification_sent = _send_email_verification(user, request)
    return JsonResponse({
        "success": True,
        "user": _user_data(user),
        "verification_email_sent": verification_sent,
        "message": (
            "Account created. Verify your email before signing in to DengueWatch."
            if verification_sent else
            "Account created, but the verification email could not be sent. Try resending it or contact the system administrator."
        ),
    }, status=201)


def _send_email_verification(user, request=None):
    """Send a time-limited link bound to the account's current email address."""
    if user.email_verified or not user.email or not settings.EMAIL_DELIVERY_ENABLED:
        return False
    now = timezone.now()
    if user.email_verification_sent_at and (now - user.email_verification_sent_at).total_seconds() < 60:
        return False
    signer = signing.TimestampSigner(salt='denguewatch.resident-email-verification')
    email_digest = salted_hmac('denguewatch.resident-email-verification', user.email).hexdigest()
    signed_token = signer.sign(f'{user.pk}:{email_digest}')
    if request is not None:
        verify_path = reverse('api_mobile_verify_email')
        link = request.build_absolute_uri(
            f'{verify_path}?{urlencode({"token": signed_token})}'
        )
    else:
        link = f'{settings.MOBILE_VERIFICATION_LINK_BASE}/{signed_token}'
    display_name = user.first_name or user.username or 'DengueWatch user'
    text_body = (
        f'Hello {display_name},\n\n'
        'Confirm your registration of the DengueWatch application by clicking the link below.\n\n'
        f'Verify your email: {link}\n\n'
        'This link expires in 24 hours. If you did not create this account, ignore this email.'
    )
    html_body = (
        '<div style="font-family:Arial,sans-serif;line-height:1.6">'
        f'<p>Hello {escape(display_name)},</p>'
        '<p>Confirm your registration of the DengueWatch application by clicking the link below.</p>'
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 18px;'
        'background:#0d6b57;color:#fff;text-decoration:none;border-radius:6px">'
        'Verify email in DengueWatch</a></p>'
        '<p>This link expires in 24 hours. If you did not create this account, ignore this email.</p></div>'
    )
    try:
        email = EmailMultiAlternatives(
            'Verify your DengueWatch email address',
            text_body,
            settings.DEFAULT_FROM_EMAIL or None,
            [user.email],
        )
        email.attach_alternative(html_body, 'text/html')
        if email.send(fail_silently=False):
            user.email_verification_sent_at = now
            user.save(update_fields=['email_verification_sent_at'])
            return True
    except Exception:
        return False
    return False


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def verify_resident_email(request):
    if request.method == 'GET':
        signed_token = request.GET.get('token', '').strip()
        if not signed_token:
            return _verification_html(
                'Verification link unavailable',
                'The verification link is missing its token. Request a new email and try again.',
            )
        return _verification_html(
            'Verify your email address',
            'Select the button below to confirm this email address for your DengueWatch account.',
            token=signed_token,
        )

    data = _body(request)
    if data is None:
        data = request.POST
    signed_token = str((data or {}).get('token', '')).strip()
    if not signed_token:
        return _error('Verification link is missing its token.')
    signer = signing.TimestampSigner(salt='denguewatch.resident-email-verification')
    try:
        value = signer.unsign(signed_token, max_age=60 * 60 * 24)
        user_id, token_digest = value.split(':', 1)
        user = UserAccount.objects.get(pk=int(user_id))
    except (signing.BadSignature, ValueError, UserAccount.DoesNotExist):
        if request.content_type != 'application/json':
            return _verification_html(
                'Verification link unavailable',
                'This verification link is invalid or expired. Request a new email and try again.',
            )
        return _error('This verification link is invalid or expired. Request a new one.', status=400)
    current_digest = salted_hmac('denguewatch.resident-email-verification', user.email).hexdigest()
    if not constant_time_compare(token_digest, current_digest):
        if request.content_type != 'application/json':
            return _verification_html(
                'Verification link unavailable',
                'This link no longer matches the email address on the account. Request a new email.',
            )
        return _error('This verification link is no longer valid for the current email address.', status=400)
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=['email_verified'])
        from .admin_notifications import notify_cho_admins
        role_label = user.get_role_display()
        status_label = user.get_account_status_display()
        notify_cho_admins(
            title='Account email verified',
            message=f'{user.get_full_name() or user.username} ({role_label}) verified their email. Account status: {status_label}.',
            link='/cho/pending-requests/' if user.account_status == 'PENDING' else '/user-management/',
            actor=user if user.role == 'CHO' else None,
            notification_type='ADMIN',
        )
    if request.content_type != 'application/json':
        return _verification_html(
            'Email verified',
            'Your DengueWatch email address is verified. You can now continue to sign in or wait for CHO approval if your account is pending.',
        )
    return JsonResponse({'success': True, 'message': 'Email verified. You can now use your account or wait for CHO approval if it is pending.'})


def _verification_html(title, message, token=''):
    token_input = (
        f'<input type="hidden" name="token" value="{escape(token)}">'
        '<button type="submit" style="display:inline-block;padding:12px 18px;'
        'background:#0d6b57;color:#fff;border:0;border-radius:6px;font-size:16px">'
        'Verify email in DengueWatch</button>'
        if token else ''
    )
    action = f'<form method="post">{token_input}</form>' if token else ''
    html = (
        '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta charset="utf-8"><title>DengueWatch email verification</title>'
        '<body style="margin:0;background:#f3f6f8;font:16px Arial,sans-serif;color:#1f2937">'
        '<main style="max-width:520px;margin:10vh auto;padding:28px;background:#fff;border-radius:14px">'
        '<h1 style="font-size:24px">' + escape(title) + '</h1>'
        '<p style="line-height:1.6">' + escape(message) + '</p>' + action +
        '</main></body></html>'
    )
    return HttpResponse(html)


@csrf_exempt
@require_http_methods(['POST'])
def resend_email_verification(request):
    data = _body(request)
    if data is None:
        return _error('Invalid JSON body.')
    if not settings.EMAIL_DELIVERY_ENABLED:
        return _error('Email delivery is not configured. Contact the system administrator.', status=503)

    # A newly registered resident has no session until verification succeeds.
    # Also keep the authenticated profile-page resend flow working.
    header = request.headers.get('Authorization', '')
    raw_token = header[7:].strip() if header.startswith('Bearer ') else ''
    user = MobileAccessToken.authenticate(raw_token) if raw_token else None
    if user is None:
        email = str(data.get('email', '')).strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            return _error('Enter a valid email address.')
        user = UserAccount.objects.filter(email__iexact=email, role='RESIDENT').first()
        if user is None or user.email_verified:
            return JsonResponse({
                'success': True,
                'message': 'If this address belongs to an unverified resident account, a verification email will be sent.',
            })
    if user.email_verified:
        return JsonResponse({
            'success': True,
            'message': 'Your email is already verified.' if raw_token else
                'If this address belongs to an unverified resident account, a verification email will be sent.',
        })

    if user.email_verification_sent_at and (timezone.now() - user.email_verification_sent_at).total_seconds() < 60:
        if not raw_token:
            return JsonResponse({
                'success': True,
                'message': 'If this address belongs to an unverified resident account, a verification email will be sent.',
            })
        return _error('Wait one minute before requesting another verification email.', status=429)
    if not _send_email_verification(user, request):
        if not raw_token:
            return JsonResponse({
                'success': True,
                'message': 'If this address belongs to an unverified resident account, a verification email will be sent.',
            })
        return _error('Could not send the verification email. Try again later.', status=502)
    return JsonResponse({
        'success': True,
        'message': f'Verification email sent to {user.email}.' if raw_token else
            'If this address belongs to an unverified resident account, a verification email will be sent.',
    })


@csrf_exempt
@require_http_methods(["POST"])
def login_mobile(request):
    data = _body(request)
    if data is None:
        return _error("Invalid JSON body.")
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = authenticate(request, username=email, password=password)
    if not user:
        return _error("Incorrect email or password.", status=401)
    if user.role != "RESIDENT":
        return _error(
            "Staff accounts must sign in through the DengueWatch desktop web system.",
            status=403,
        )
    if not user.email_verified:
        return _error(
            "Please verify your email address using the link sent to you before signing in.",
            status=403,
        )
    if user.account_status != "APPROVED":
        return _error("This account is not yet approved.", status=403)
    token = MobileAccessToken.issue(user)
    return JsonResponse({"success": True, "token": token, "user": _user_data(user)})


@csrf_exempt
@mobile_auth
@require_http_methods(["POST"])
def logout_mobile(request):
    import hashlib
    token_hash = hashlib.sha256(request.mobile_raw_token.encode()).hexdigest()
    MobileAccessToken.objects.filter(token_hash=token_hash).update(revoked_at=timezone.now())
    return JsonResponse({"success": True, "message": "Logged out successfully."})


@mobile_auth
@require_http_methods(["GET"])
def me(request):
    return JsonResponse({"success": True, "user": _user_data(request.mobile_user)})


@csrf_exempt
@mobile_auth
@require_http_methods(["POST"])
def update_profile(request):
    """Allow a resident to update only their permitted account details."""
    user = request.mobile_user
    email = str(request.POST.get("email", "")).strip().lower()
    contact_number = str(request.POST.get("contact_number", "")).strip()
    address = str(request.POST.get("address", "")).strip()

    if not email:
        return _error("Email address is required.", fields={"email": "Required."})
    try:
        validate_email(email)
    except ValidationError:
        return _error("Enter a valid email address.", fields={"email": "Invalid email address."})
    if len(contact_number) > 20:
        return _error("Mobile number must contain at most 20 characters.")
    if UserAccount.objects.exclude(pk=user.pk).filter(
        Q(email__iexact=email) | Q(username__iexact=email)
    ).exists():
        return _error("An account with this email already exists.", status=409)

    picture = request.FILES.get("profile_picture")
    if picture:
        if not (picture.content_type or "").startswith("image/"):
            return _error("Profile picture must be an image file.")
        if picture.size > 5 * 1024 * 1024:
            return _error("Profile picture must be 5 MB or smaller.")
        user.profile_picture = picture

    # Deliberately do not accept name, role, assigned area, status, or password
    # in this resident self-service endpoint.
    email_changed = email.casefold() != user.email.casefold()
    user.email = email
    if email_changed:
        user.email_verified = False
        user.email_verification_sent_at = None
    user.username = email
    user.contact_number = contact_number
    user.address = address
    update_fields = ["email", "username", "contact_number", "address"]
    if email_changed:
        update_fields.extend(["email_verified", "email_verification_sent_at"])
    if picture:
        update_fields.append("profile_picture")
    user.save(update_fields=update_fields)
    verification_sent = _send_email_verification(user, request) if email_changed else False
    return JsonResponse({"success": True, "user": _user_data(user), "verification_email_sent": verification_sent})


@require_http_methods(["GET"])
def locations(request):
    """Return a lightweight barangay list for the mobile registration form."""
    barangays = Barangay.objects.filter(
        barangay_name__in=ILIGAN_BARANGAYS
    ).order_by("barangay_name")
    items = [{
        "id": b.pk,
        "name": b.barangay_name,
        "latitude": float(b.latitude) if b.latitude is not None else None,
        "longitude": float(b.longitude) if b.longitude is not None else None,
        "puroks": [],
    } for b in barangays]
    return JsonResponse({"success": True, "barangays": items})


@require_http_methods(["GET"])
def barangay_puroks(request, barangay_id):
    """Return only the Purok/Sitio records for one selected barangay."""
    barangay = Barangay.objects.filter(pk=barangay_id).first()
    if not barangay:
        return _error("Selected barangay was not found.", status=404)
    puroks = Purok.objects.filter(barangay=barangay).order_by("purok_name")
    return JsonResponse({
        "success": True,
        "barangay_id": barangay.pk,
        "puroks": [{"id": p.pk, "name": p.purok_name} for p in puroks],
    })


@require_http_methods(["GET"])
def iligan_barangay_boundaries(request):
    """Local, token-free GeoJSON used by both the web and Expo maps."""
    path = Path(settings.BASE_DIR) / "static" / "data" / "iligan_barangays.geojson"
    try:
        return JsonResponse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return _error("The local Iligan boundary map is unavailable.", status=503)


@require_http_methods(["GET"])
def public_hotspot_preview(request):
    """Expose only aggregated 2026 barangay hotspot data for the public app welcome map."""
    request.GET = request.GET.copy()
    request.GET["year"] = "2026"
    request.GET["risk"] = "all"
    historical = build_hotspot_data(request)
    centers = _official_barangay_centers()
    # build_hotspot_data falls back to all years when a requested year is not
    # present. Never let that behavior leak a different period into this fixed
    # public preview.
    preview_rows = historical["hotspot_data"] if historical.get("selected_year") == "2026" else []
    items = [
        _historical_map_item(index, item, centers)
        for index, item in enumerate(preview_rows, start=1)
    ]
    return JsonResponse({
        "success": True,
        "source": "historical_dataset",
        "selected_year": "2026",
        "selected_year_label": "Historical year 2026",
        "map_data_source": "Aggregated historical dengue case records",
        "hotspots": items,
    })


@require_http_methods(["GET"])
def public_monthly_critical_areas(request):
    """Return monthly barangay aggregates meeting the existing Critical band."""
    dataset_path = Path(settings.BASE_DIR) / "datasets" / "integrated_monthly.csv"
    try:
        with dataset_path.open("r", encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
    except (OSError, csv.Error):
        return _error("Monthly dengue case data is unavailable.", status=503)

    # Use only cells explicitly confirmed by CHO or containing a line-list
    # count. Unverified missing cells must not be treated as zero cases.
    valid_statuses = {"cases_present_line_list_count", "zero_confirmed_by_cho"}
    clean_rows = [
        row for row in rows
        if str(row.get("year", "")).strip().isdigit()
        and str(row.get("month", "")).strip().isdigit()
        and str(row.get("case_observation_status", "")).strip() in valid_statuses
        and canonicalize_barangay(row.get("barangay", ""))
    ]
    confirmed_cases = DengueCase.objects.filter(
        case_status="Confirmed",
        barangay__isnull=False,
    ).exclude(
        user_account__username="dataset_importer",
        remarks__istartswith="Imported from workbook",
    ).select_related("barangay", "user_account")

    current_year = timezone.localdate().year
    monthly_counts = {}
    for row in clean_rows:
        year = int(row["year"])
        month = int(row["month"])
        if year != current_year or not 1 <= month <= 12:
            continue
        barangay = canonicalize_barangay(row["barangay"])
        try:
            count = max(0, int(float(row.get("case_count") or 0)))
        except (TypeError, ValueError):
            continue
        month_counts = monthly_counts.setdefault(month, {})
        month_counts[barangay] = month_counts.get(barangay, 0) + count

    for case in confirmed_cases:
        year = case.date_reported.year
        month = case.date_reported.month
        if year != current_year:
            continue
        barangay = canonicalize_barangay(case.barangay.barangay_name)
        if not barangay:
            continue
        month_counts = monthly_counts.setdefault(month, {})
        month_counts[barangay] = month_counts.get(barangay, 0) + max(1, int(case.case_count or 1))

    month_labels = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    months = []
    for month in sorted(monthly_counts):
        areas = [
            {"barangay": barangay, "case_count": count}
            for barangay, count in sorted(monthly_counts[month].items())
            if count >= 101
        ]
        months.append({"month": month, "label": month_labels[month - 1], "critical_barangays": areas})

    return JsonResponse({
        "success": True,
        "year": current_year,
        "data_through_month": month_labels[max(monthly_counts) - 1] if monthly_counts else None,
        "threshold_cases": 101,
        "months": months,
    })


@mobile_auth
@require_http_methods(["GET"])
def hotspots(request):
    # Residents see the same historical case-volume classifications as the
    # CHO/LGU heat map. Forecasts remain available to staff as planning data,
    # but must not replace the historical map view on the mobile app.
    if request.GET.get('source') == 'historical':
        historical = build_hotspot_data(request)
        centers = _official_barangay_centers()
        items = [
            _historical_map_item(index, item, centers)
            for index, item in enumerate(historical['hotspot_data'], start=1)
        ]
        return JsonResponse({
            "success": True,
            "source": "historical_dataset",
            "case_data_period": historical['historical_case_period'],
            "historical_case_period": historical['historical_case_period'],
            "selected_year": historical['selected_year'],
            "selected_year_label": historical['selected_year_label'],
            "available_years": historical['available_years'],
            "total_cases": historical['total_cases'],
            "dataset_quality": historical.get('dataset_quality'),
            "map_data_source": historical['map_data_source'],
            "hotspots": items,
        })

    context = prediction_context(request)
    if context.get("model_ready"):
        coordinates = {
            item.barangay_name: item
            for item in Barangay.objects.filter(barangay_name__in=ILIGAN_BARANGAYS)
        }
        items = []
        for index, forecast in enumerate(context["forecasts"], start=1):
            name = canonicalize_barangay(forecast["barangay"])
            if not name:
                continue
            barangay = coordinates.get(name)
            items.append({
                "id": index,
                "barangay_id": barangay.pk if barangay else None,
                "barangay": name,
                "forecast_period": context["forecast_period"],
                "case_data_period": context["case_data_period"],
                "predicted_cases": forecast["predicted_cases"],
                "is_potential_hotspot": (
                    forecast["predicted_cases"] >= context["predicted_hotspot_threshold"]
                ),
                "current_cases": forecast["current_cases"],
                "case_change": forecast["case_change"],
                "trend": forecast["trend"],
                "risk_level": forecast["risk_level"],
                "rainfall_mm": forecast["rainfall_mm"],
                "temperature_c": forecast["temperature_c"],
                "humidity_pct": forecast["humidity_pct"],
                "recommendation": forecast["recommendation"],
                # Aggregate historical context only—never an individual risk
                # score, diagnosis, or personally identifiable record.
                "historical_aggregate_common_blood_type": forecast.get(
                    "historical_common_blood_type",
                ),
                "blood_type_feature_notice": BLOOD_TYPE_FEATURE_NOTICE,
                "latitude": float(barangay.latitude) if barangay and barangay.latitude is not None else None,
                "longitude": float(barangay.longitude) if barangay and barangay.longitude is not None else None,
            })
        return JsonResponse({
            "success": True,
            "source": "random_forest_model",
            "forecast_period": context["forecast_period"],
            "case_data_period": context["case_data_period"],
            "prediction_definition": PREDICTION_DEFINITION,
            "predicted_hotspot_threshold_cases": context["predicted_hotspot_threshold"],
            "potential_hotspot_count": len(context.get("potential_hotspots", [])),
            "weather": context.get("weather", {}),
            "blood_type_by_year": context.get("blood_type_by_year", []),
            "blood_type_feature_notice": BLOOD_TYPE_FEATURE_NOTICE,
            "hotspots": items,
        })

    # When the ML artifact is unavailable, keep the map usable with the same
    # official 44-barangay, historical-data view used by the CHO and LGU web
    # hotspot pages. This is deliberately labeled as historical, not AI output.
    historical = build_hotspot_data(request)
    if historical['hotspot_data']:
        centers = _official_barangay_centers()
        items = [
            _historical_map_item(index, item, centers)
            for index, item in enumerate(historical['hotspot_data'], start=1)
        ]
        return JsonResponse({
            "success": True,
            "source": "historical_dataset",
            "case_data_period": historical['historical_case_period'],
            "historical_case_period": historical['historical_case_period'],
            "selected_year": historical['selected_year'],
            "selected_year_label": historical['selected_year_label'],
            "map_data_source": historical['map_data_source'],
            "warning": context.get("prediction_error", ""),
            "hotspots": items,
        })

    # Database fallback supports manually saved predictions when no source
    # dataset is available.
    latest_ids = []
    for barangay_id in Barangay.objects.filter(
        barangay_name__in=ILIGAN_BARANGAYS
    ).values_list("pk", flat=True):
        latest = HotspotPrediction.objects.filter(barangay_id=barangay_id).order_by("-prediction_date", "-pk").first()
        if latest:
            latest_ids.append(latest.pk)
    predictions = HotspotPrediction.objects.filter(pk__in=latest_ids).select_related("barangay")
    items = [{
        "id": item.pk,
        "barangay_id": item.barangay_id,
        "barangay": item.barangay.barangay_name,
        "prediction_date": item.prediction_date.isoformat(),
        "risk_score": item.risk_score,
        "risk_level": item.risk_level or item.hotspot_level,
        "forecast_result": item.forecast_result,
        "analysis_remarks": item.analysis_remarks,
        "latitude": float(item.latitude) if item.latitude is not None else None,
        "longitude": float(item.longitude) if item.longitude is not None else None,
    } for item in predictions]
    return JsonResponse({
        "success": True,
        "source": "saved_predictions",
        "warning": context.get("prediction_error", ""),
        "hotspots": items,
    })


@mobile_auth
@require_http_methods(["GET"])
def alerts(request):
    user = request.mobile_user
    now = timezone.now()
    queryset = Alert.objects.filter(is_active=True, cho_review_confirmed=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).filter(Q(barangay__isnull=True) | Q(barangay_id=user.assigned_barangay_id)).select_related("barangay")
    items = [{
        "id": item.pk,
        "title": item.title,
        "message": item.message,
        "risk_level": item.risk_level,
        "barangay": item.barangay.barangay_name if item.barangay else "All Iligan City",
        "created_at": item.created_at.isoformat(),
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
    } for item in queryset.order_by("-created_at")[:100]]
    return JsonResponse({"success": True, "alerts": items})


@mobile_auth
@require_http_methods(["GET"])
def alert_detail(request, alert_id):
    """Return one active alert only to residents inside its intended audience."""
    user = request.mobile_user
    now = timezone.now()
    alert = get_object_or_404(
        Alert.objects.select_related("barangay"),
        pk=alert_id,
        is_active=True,
        cho_review_confirmed=True,
    )
    if alert.expires_at and alert.expires_at <= now:
        return _error("This alert is no longer active.", status=404)
    if alert.barangay_id and alert.barangay_id != user.assigned_barangay_id:
        return _error("This alert is not available for your area.", status=404)
    return JsonResponse({"success": True, "alert": {
        "id": alert.pk,
        "title": alert.title,
        "message": alert.message,
        "risk_level": alert.risk_level,
        "barangay": alert.barangay.barangay_name if alert.barangay else "All Iligan City",
        "created_at": alert.created_at.isoformat(),
        "expires_at": alert.expires_at.isoformat() if alert.expires_at else None,
    }})


@csrf_exempt
@mobile_auth
@require_http_methods(["GET", "POST"])
def notifications(request):
    """Resident in-app notifications, including replies from CHO."""
    user = request.mobile_user
    if request.method == "POST":
        data = _body(request)
        if data is None:
            return _error("Invalid JSON body.")
        ids = data.get("ids", [])
        if not isinstance(ids, list):
            return _error("Notification ids must be a list.")
        SystemNotification.objects.filter(
            recipient=user, notification_id__in=ids, is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        return JsonResponse({"success": True})

    visible_alerts = Alert.objects.filter(
        is_active=True,
        cho_review_confirmed=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).filter(
        Q(barangay__isnull=True) | Q(barangay_id=user.assigned_barangay_id)
    ).values_list('pk', flat=True)
    visible_notifications = SystemNotification.objects.filter(recipient=user).filter(
        ~Q(notification_type='ALERT')
        | Q(link__in=[f'/alert/{alert_id}' for alert_id in visible_alerts])
    )
    items = [{
        "id": item.notification_id,
        "type": item.notification_type,
        "title": item.title,
        "message": item.message,
        "link": item.link,
        "is_read": item.is_read,
        "created_at": item.created_at.isoformat(),
    } for item in visible_notifications[:100]]
    return JsonResponse({"success": True, "notifications": items})


@csrf_exempt
@mobile_auth
@require_http_methods(["GET", "POST"])
def community_reports(request):
    user = request.mobile_user
    if request.method == "GET":
        reports = CommunityReport.objects.filter(resident=user).select_related("barangay", "purok").prefetch_related("audit_logs__actor")
        items = [{
            "id": item.pk,
            "observation_type": item.observation_type,
            "description": item.description,
            "location_details": item.location_details,
            "photo_url": request.build_absolute_uri(item.photo.url) if item.photo else None,
            "latitude": float(item.latitude) if item.latitude is not None else None,
            "longitude": float(item.longitude) if item.longitude is not None else None,
            "barangay": item.barangay.barangay_name,
            "purok": item.purok.purok_name if item.purok else None,
            "status": item.status,
            "staff_response": item.staff_response,
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "submitted_at": item.submitted_at.isoformat(),
            "audit_trail": [{
                "action": audit.action,
                "details": audit.details,
                "actor": audit.actor.get_full_name() or audit.actor.username if audit.actor else "System",
                "created_at": audit.created_at.isoformat(),
            } for audit in item.audit_logs.all()],
        } for item in reports.order_by("-submitted_at")]
        return JsonResponse({"success": True, "reports": items})

    if request.content_type and request.content_type.startswith("multipart/form-data"):
        data = request.POST
    else:
        data = _body(request)
        if data is None:
            return _error("Invalid JSON body.")
    observation_type = str(data.get("observation_type", "")).strip()
    description = str(data.get("description", "")).strip()
    location_details = str(data.get("location_details", "")).strip()[:250]
    if not observation_type or not description:
        return _error("Observation type and description are required.")
    barangay = Barangay.objects.filter(pk=data.get("barangay_id") or user.assigned_barangay_id).first()
    if not barangay:
        return _error("A valid barangay is required.")
    purok = None
    if data.get("purok_id"):
        purok = Purok.objects.filter(pk=data["purok_id"], barangay=barangay).first()
        if not purok:
            return _error("Selected purok does not belong to the barangay.")
    photo = request.FILES.get("photo")
    if photo:
        if photo.size > 5 * 1024 * 1024:
            return _error("Photo must be 5 MB or smaller.")
        try:
            with Image.open(photo) as uploaded_image:
                if uploaded_image.format not in {"JPEG", "PNG", "WEBP"}:
                    return _error("Upload a JPG, PNG, or WebP photo.")
                if uploaded_image.width * uploaded_image.height > 25_000_000:
                    return _error("Photo dimensions are too large. Choose a smaller image.")
                uploaded_image.verify()
            photo.seek(0)
        except Exception:
            return _error("The selected photo is not a valid image.")
    report = CommunityReport.objects.create(
        resident=user,
        barangay=barangay,
        purok=purok,
        observation_type=observation_type,
        description=description,
        location_details=location_details,
        photo=photo,
        latitude=data.get("latitude") or None,
        longitude=data.get("longitude") or None,
    )
    log_report_action(
        actor=user,
        community_report=report,
        action='CREATED',
        details='Resident submitted a community report.',
    )
    from .admin_notifications import notify_cho_admins
    notify_cho_admins(
        title=f'New resident {observation_type} report',
        message=f'{barangay.barangay_name}: {description[:160]}',
        actor=user,
        link='/cho/community-reports/',
        notification_type='REPORT',
    )
    return JsonResponse({"success": True, "message": "Community report submitted for verification.", "id": report.pk}, status=201)
