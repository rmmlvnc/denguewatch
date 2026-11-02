import json
from datetime import date
from pathlib import Path

from django.test import RequestFactory, TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import get_template

from .locations import ILIGAN_BARANGAYS, canonicalize_barangay
from .ml.service import BLOOD_TYPE_FEATURE_NOTICE, model_evaluation_summary
from .models import Alert, Barangay, CommunityReport, DengueCase, Purok, ReportAuditLog, SystemNotification, UserAccount
from .views import build_hotspot_data, load_dengue_cases


class MobileApiTests(TestCase):
    def setUp(self):
        self.barangay = Barangay.objects.create(barangay_name="Abuno")
        self.purok = Purok.objects.create(barangay=self.barangay, purok_name="Test Purok")

    def test_health_and_locations_are_public(self):
        health = self.client.get('/api/mobile/health/')
        locations = self.client.get('/api/mobile/locations/')
        puroks = self.client.get(f'/api/mobile/locations/{self.barangay.pk}/puroks/')

        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()['success'])
        self.assertEqual(locations.status_code, 200)
        self.assertEqual(locations.json()['barangays'][0]['puroks'], [])
        self.assertEqual(puroks.status_code, 200)
        self.assertEqual(puroks.json()['puroks'][0]['name'], 'Test Purok')

    def test_canonical_barangay_scope_is_exactly_44_official_labels(self):
        self.assertEqual(len(ILIGAN_BARANGAYS), 44)
        self.assertEqual(len(set(ILIGAN_BARANGAYS)), 44)
        self.assertEqual(canonicalize_barangay('Maria-Cristina'), 'Maria Cristina')
        self.assertIsNone(canonicalize_barangay('Old Poblacion'))

    def test_patient_dataset_loader_excludes_non_iligan_barangay_labels(self):
        cases = load_dengue_cases()
        self.assertGreater(len(cases), 0)
        self.assertTrue(all(case['barangay'] in ILIGAN_BARANGAYS for case in cases))

    def test_saray_and_tibanga_remain_distinct_canonical_barangays(self):
        cases = load_dengue_cases()
        labels = {case['barangay'] for case in cases}
        self.assertIn('Saray', labels)
        self.assertIn('Tibanga', labels)
        self.assertNotEqual(canonicalize_barangay('Saray'), canonicalize_barangay('Tibanga'))
        self.assertTrue(any(case['blood_type'] != 'N/A' for case in cases))

    def test_web_hotspot_data_has_all_44_official_barangays(self):
        context = build_hotspot_data(RequestFactory().get('/hotspot-map/'))
        labels = {item['barangay'] for item in context['hotspot_data']}
        self.assertEqual(labels, set(ILIGAN_BARANGAYS))
        self.assertEqual(context['total_barangays'], 44)
        self.assertEqual(context['map_data_source'], 'Historical dengue case records')
        self.assertTrue(context['historical_case_period'])
        self.assertEqual(context['selected_year_label'], 'All available historical years')

    def test_hotspot_coverage_counts_distinct_assigned_bhw_barangays(self):
        second_barangay = Barangay.objects.create(barangay_name='Dalipuga')
        UserAccount.objects.create_user(
            username='abuno_bhw_one', password='safe-password-123',
            role='BHW', account_status='APPROVED', assigned_barangay=self.barangay,
        )
        UserAccount.objects.create_user(
            username='abuno_bhw_two', password='safe-password-123',
            role='BHW', account_status='APPROVED', assigned_barangay=self.barangay,
        )
        UserAccount.objects.create_user(
            username='dalipuga_bhw', password='safe-password-123',
            role='BHW', account_status='APPROVED', assigned_barangay=second_barangay,
        )
        UserAccount.objects.create_user(
            username='pending_bhw', password='safe-password-123',
            role='BHW', account_status='PENDING', assigned_barangay=second_barangay,
        )

        context = build_hotspot_data(RequestFactory().get('/hotspot-map/'))

        self.assertEqual(context['bhw_covered_barangays'], 2)
        self.assertEqual(context['assigned_bhw_workers'], 3)

    def test_local_hotspot_boundaries_cover_each_official_barangay_once(self):
        boundary_path = Path(__file__).resolve().parents[1] / 'static' / 'data' / 'iligan_barangays.geojson'
        boundaries = json.loads(boundary_path.read_text(encoding='utf-8'))
        names = [feature['properties']['brgy_name'] for feature in boundaries['features']]
        self.assertEqual(len(names), 44)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(ILIGAN_BARANGAYS))
        self.assertTrue(all(feature.get('geometry') for feature in boundaries['features']))

    def test_hotspot_year_and_risk_filters_keep_all_map_boundaries_available(self):
        context = build_hotspot_data(RequestFactory().get('/hotspot-map/?year=2026&risk=critical'))
        self.assertEqual(context['selected_year'], '2026')
        self.assertEqual(context['selected_risk'], 'critical')
        self.assertEqual(len(context['hotspot_data']), 44)
        self.assertEqual(len(json.loads(context['map_locations_json'])), 44)

    def test_only_cho_confirmed_web_cases_update_live_case_aggregates(self):
        chw = UserAccount.objects.create_user(
            username='chw-live-case',
            password='safe-password-123',
            role='CHW',
            account_status='APPROVED',
        )
        common_fields = {
            'user_account': chw,
            'barangay': self.barangay,
            'purok': self.purok,
            'patient_age': 28,
            'patient_sex': 'Female',
            'date_reported': date(2030, 1, 10),
        }
        DengueCase.objects.create(
            **common_fields,
            case_status='Pending',
            case_count=9,
        )
        DengueCase.objects.create(
            **common_fields,
            case_status='Confirmed',
            case_count=2,
        )

        context = build_hotspot_data(
            RequestFactory().get('/hotspot-map/?year=2030')
        )
        abuno = next(
            item for item in context['hotspot_data']
            if item['barangay'] == 'Abuno'
        )
        live_cases = [
            case for case in load_dengue_cases()
            if case['source_file'] == 'CHO-confirmed web record'
            and case['year'] == '2030'
        ]

        self.assertEqual(context['selected_year'], '2030')
        self.assertEqual(abuno['case_count'], 2)
        self.assertEqual(len(live_cases), 2)

    def test_web_api_preflight_is_allowed(self):
        response = self.client.options(
            '/api/mobile/auth/register/',
            HTTP_ORIGIN='http://localhost:8081',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['Access-Control-Allow-Origin'], 'http://localhost:8081')

    def test_new_resident_must_verify_email_before_signing_in(self):
        response = self.client.post(
            '/api/mobile/auth/register/',
            data=json.dumps({
                'first_name': 'Ada',
                'last_name': 'Resident',
                'email': 'ada@example.com',
                'password': 'safe-password-123',
                'barangay_id': self.barangay.pk,
                'purok_id': self.purok.pk,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn('token', response.json())
        self.assertFalse(response.json()['user']['email_verified'])
        login = self.client.post(
            '/api/mobile/auth/login/',
            data=json.dumps({'email': 'ada@example.com', 'password': 'safe-password-123'}),
            content_type='application/json',
        )
        self.assertEqual(login.status_code, 403)
        self.assertIn('verify your email', login.json()['message'].lower())

    def test_historical_hotspots_include_official_boundary_coordinates(self):
        UserAccount.objects.create_user(
            username='map@example.com', email='map@example.com',
            password='safe-password-123', role='RESIDENT',
            account_status='APPROVED', assigned_barangay=self.barangay,
            email_verified=True,
        )
        login = self.client.post(
            '/api/mobile/auth/login/',
            data=json.dumps({'email': 'map@example.com', 'password': 'safe-password-123'}),
            content_type='application/json',
        )
        response = self.client.get(
            '/api/mobile/hotspots/?source=historical',
            HTTP_AUTHORIZATION=f"Bearer {login.json()['token']}",
        )

        self.assertEqual(response.status_code, 200)
        hotspots = response.json()['hotspots']
        self.assertEqual(len(hotspots), 44)
        self.assertTrue(all(item['latitude'] is not None and item['longitude'] is not None for item in hotspots))

    def test_resident_registration_saves_without_a_purok(self):
        response = self.client.post(
            '/api/mobile/auth/register/',
            data=json.dumps({
                'first_name': 'No',
                'last_name': 'Purok',
                'email': 'no-purok@example.com',
                'password': 'safe-password-123',
                'barangay_id': self.barangay.pk,
                'address': 'Test address',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        resident = UserAccount.objects.get(email='no-purok@example.com')
        self.assertEqual(resident.role, 'RESIDENT')
        self.assertEqual(resident.assigned_barangay, self.barangay)
        self.assertIsNone(resident.assigned_purok)

    def test_resident_can_update_only_allowed_mobile_profile_fields(self):
        resident = UserAccount.objects.create_user(
            username='profile@example.com', email='profile@example.com',
            password='safe-password-123', role='RESIDENT',
            account_status='APPROVED', assigned_barangay=self.barangay,
            first_name='Original', last_name='Resident', address='Old address',
            email_verified=True,
        )
        login = self.client.post(
            '/api/mobile/auth/login/',
            data=json.dumps({'email': 'profile@example.com', 'password': 'safe-password-123'}),
            content_type='application/json',
        )
        token = login.json()['token']
        response = self.client.post(
            '/api/mobile/profile/',
            data={
                'email': 'updated@example.com',
                'contact_number': '09171234567',
                'address': 'Updated address',
                'profile_picture': SimpleUploadedFile('profile.jpg', b'image-data', content_type='image/jpeg'),
                # This is intentionally ignored by the self-service endpoint.
                'first_name': 'Changed',
            },
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 200)
        resident.refresh_from_db()
        self.assertEqual(resident.email, 'updated@example.com')
        self.assertEqual(resident.username, 'updated@example.com')
        self.assertEqual(resident.contact_number, '09171234567')
        self.assertEqual(resident.address, 'Updated address')
        self.assertEqual(resident.first_name, 'Original')
        self.assertTrue(resident.profile_picture.name.startswith('profile_pictures/profile'))
        self.assertEqual(response.json()['user']['profile_picture'], resident.profile_picture.url)

    def test_resident_registration_accepts_an_official_barangay_name_without_an_id(self):
        response = self.client.post(
            '/api/mobile/auth/register/',
            data=json.dumps({
                'first_name': 'Name',
                'last_name': 'Fallback',
                'email': 'name-fallback@example.com',
                'password': 'safe-password-123',
                'barangay_name': 'Abuno',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            UserAccount.objects.get(email='name-fallback@example.com').assigned_barangay,
            self.barangay,
        )


class ChwSuspectedCaseWorkflowTests(TestCase):
    def setUp(self):
        self.barangay = Barangay.objects.create(barangay_name='Tubod')
        self.purok = Purok.objects.create(barangay=self.barangay, purok_name='Purok 1')
        self.chw = UserAccount.objects.create_user(
            username='chw_reporter', password='safe-password-123', role='CHW', account_status='APPROVED'
        )
        self.cho = UserAccount.objects.create_user(
            username='cho_reviewer', password='safe-password-123', role='CHO', account_status='APPROVED'
        )
        self.payload = {
            'patient_age': '28', 'patient_sex': 'Female', 'patient_blood_type': 'O+',
            'date_reported': '2026-10-06', 'barangay_id': str(self.barangay.pk),
            'purok_id': str(self.purok.pk), 'location_details': 'Near the covered court',
            'remarks': 'Follow-up requested',
        }

    def test_chw_can_save_a_draft_then_send_it_to_cho(self):
        self.client.force_login(self.chw)
        response = self.client.post('/chw/suspected-cases/', data={**self.payload, 'action': 'draft'})
        self.assertRedirects(response, '/chw/suspected-cases/')
        report = DengueCase.objects.get(user_account=self.chw)
        self.assertEqual(report.case_status, 'Draft')
        response = self.client.post(
            f'/chw/suspected-cases/{report.pk}/update/', data={**self.payload, 'action': 'submit'}
        )
        self.assertRedirects(response, '/chw/suspected-cases/')
        report.refresh_from_db()
        self.assertEqual(report.case_status, 'Pending')
        self.assertFalse(report.symptoms)
        self.assertEqual(report.location_details, self.payload['location_details'])
        self.assertTrue(ReportAuditLog.objects.filter(
            dengue_case=report, actor=self.chw, action='SUBMITTED'
        ).exists())

    def test_only_cho_can_make_the_final_decision(self):
        report = DengueCase.objects.create(
            user_account=self.chw, barangay=self.barangay, purok=self.purok,
            patient_age=28, patient_sex='Female', date_reported='2026-10-06',
            case_status='Pending', symptoms='Fever', location_details='Near the covered court',
        )
        self.client.force_login(self.chw)
        denied = self.client.post(
            f'/cho/suspected-cases/{report.pk}/review/',
            data={'decision': 'Confirmed', 'cho_review_note': 'Verified.'},
        )
        self.assertEqual(denied.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.case_status, 'Pending')

        self.client.force_login(self.cho)
        approved = self.client.post(
            f'/cho/suspected-cases/{report.pk}/review/',
            data={'decision': 'Confirmed', 'cho_review_note': 'Verified after CHO review.'},
        )
        self.assertRedirects(approved, '/cho/suspected-cases/')
        report.refresh_from_db()
        self.assertEqual(report.case_status, 'Confirmed')
        self.assertEqual(report.reviewed_by, self.cho)
        self.assertTrue(SystemNotification.objects.filter(
            recipient=self.chw, notification_type='CASE', title__contains='confirmed'
        ).exists())


class BhwEnvironmentalReportWorkflowTests(TestCase):
    def setUp(self):
        self.tubod = Barangay.objects.create(barangay_name='Tubod')
        self.tubod_purok = Purok.objects.create(barangay=self.tubod, purok_name='Purok 1')
        self.other_purok = Purok.objects.create(barangay=self.tubod, purok_name='Purok 2')
        self.dalipuga = Barangay.objects.create(barangay_name='Dalipuga')
        self.resident = UserAccount.objects.create_user(username='resident_reporter', password='safe-password-123', role='RESIDENT')
        self.bhw = UserAccount.objects.create_user(
            username='tubod_bhw', password='safe-password-123', role='BHW', account_status='APPROVED',
            assigned_barangay=self.tubod, assigned_purok=self.tubod_purok,
        )
        self.cho = UserAccount.objects.create_user(
            username='community_cho', password='safe-password-123', role='CHO', account_status='APPROVED'
        )
        self.in_area = CommunityReport.objects.create(
            resident=self.resident, barangay=self.tubod, purok=self.tubod_purok,
            observation_type='Standing water', description='Water collected beside the road.',
        )
        self.out_of_area = CommunityReport.objects.create(
            resident=self.resident, barangay=self.tubod, purok=self.other_purok,
            observation_type='Uncollected waste', description='Waste beside the street.',
        )

    def test_bhw_can_forward_only_a_report_in_their_assigned_purok(self):
        self.client.force_login(self.bhw)
        page = self.client.get('/bhw/environmental-reports/')
        self.assertContains(page, 'Standing water')
        self.assertNotContains(page, 'Uncollected waste')
        response = self.client.post(
            f'/bhw/environmental-reports/{self.in_area.pk}/forward/',
            data={'bhw_review_note': 'Standing water verified during area visit.'},
        )
        self.assertRedirects(response, '/bhw/environmental-reports/')
        self.in_area.refresh_from_db()
        self.assertEqual(self.in_area.status, 'FORWARDED')
        self.assertEqual(self.in_area.bhw_reviewed_by, self.bhw)
        self.assertTrue(ReportAuditLog.objects.filter(
            community_report=self.in_area, actor=self.bhw, action='FORWARDED'
        ).exists())
        self.assertTrue(SystemNotification.objects.filter(
            recipient=self.resident, notification_type='REPORT',
            title__contains='verified by BHW',
        ).exists())

        denied = self.client.post(
            f'/bhw/environmental-reports/{self.out_of_area.pk}/forward/',
            data={'bhw_review_note': 'Attempt outside assigned purok.'},
        )
        self.assertEqual(denied.status_code, 404)
        self.out_of_area.refresh_from_db()
        self.assertEqual(self.out_of_area.status, 'PENDING')

    def test_cho_finalizes_only_a_bhw_forwarded_report(self):
        self.client.force_login(self.cho)
        pending_response = self.client.post(
            f'/cho/community-reports/{self.in_area.pk}/review/',
            data={'status': 'VERIFIED', 'staff_response': 'Action planned.'},
        )
        self.assertEqual(pending_response.status_code, 404)
        self.in_area.status = 'FORWARDED'
        self.in_area.bhw_reviewed_by = self.bhw
        self.in_area.bhw_review_note = 'Verified by BHW.'
        self.in_area.save()
        final_response = self.client.post(
            f'/cho/community-reports/{self.in_area.pk}/review/',
            data={'status': 'VERIFIED', 'staff_response': 'CHO has scheduled follow-up.'},
        )
        self.assertRedirects(final_response, '/cho/community-reports/')
        self.in_area.refresh_from_db()
        self.assertEqual(self.in_area.status, 'VERIFIED')
        self.assertEqual(self.in_area.reviewed_by, self.cho)
        self.assertTrue(ReportAuditLog.objects.filter(
            community_report=self.in_area, actor=self.cho, action='VERIFIED'
        ).exists())
        self.assertTrue(SystemNotification.objects.filter(
            recipient=self.resident, notification_type='REPLY', title__contains='CHO replied'
        ).exists())


class RoleSidebarTests(TestCase):
    def dashboard_response(self, role, url):
        user = UserAccount.objects.create_user(
            username=f'{role.lower()}_user',
            password='safe-password-123',
            first_name=role,
            last_name='Tester',
            role=role,
            account_status='APPROVED',
        )
        self.client.force_login(user)
        return self.client.get(url)

    def test_each_role_dashboard_displays_the_signed_in_user(self):
        pages = [
            ('CHO', '/dashboard/cho/'),
            ('CHW', '/dashboard/chw/'),
            ('BHW', '/dashboard/bhw/'),
            ('LGU', '/lgu-dashboard/'),
        ]
        for role, url in pages:
            with self.subTest(role=role):
                response = self.dashboard_response(role, url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'{role} Tester')
                self.assertContains(response, UserAccount.ROLE_CHOICES[[item[0] for item in UserAccount.ROLE_CHOICES].index(role)][1])

    def test_every_dashboard_template_compiles(self):
        templates_dir = Path(__file__).resolve().parent / 'templates'
        templates = list(templates_dir.glob('*.html'))
        self.assertGreater(len(templates), 0)
        for template in templates:
            with self.subTest(template=template.name):
                get_template(template.name)


class ChoAuthorityTests(TestCase):
    def setUp(self):
        self.cho = UserAccount.objects.create_user(
            username='alert_cho', password='safe-password-123', role='CHO', account_status='APPROVED'
        )
        self.chw = UserAccount.objects.create_user(
            username='alert_chw', password='safe-password-123', role='CHW', account_status='APPROVED'
        )

    def test_only_cho_can_publish_or_withdraw_an_alert(self):
        self.client.force_login(self.chw)
        denied = self.client.post('/cho/alerts/create/', {
            'title': 'Not permitted', 'message': 'A CHW must not publish alerts.', 'risk_level': 'HIGH',
        })
        self.assertEqual(denied.status_code, 302)
        self.assertEqual(Alert.objects.count(), 0)

        self.client.force_login(self.cho)
        created = self.client.post('/cho/alerts/create/', {
            'title': 'Prevent standing water', 'message': 'Remove standing water around homes.', 'risk_level': 'HIGH',
            'cho_review_confirmed': 'on',
            'cho_review_note': 'Reviewed verified reports and approved prevention guidance.',
        })
        self.assertRedirects(created, '/cho/alerts/')
        alert = Alert.objects.get()
        self.assertEqual(alert.created_by, self.cho)
        self.assertTrue(alert.is_active)
        self.assertTrue(alert.cho_review_confirmed)
        self.assertEqual(alert.cho_reviewed_by, self.cho)

        withdrawn = self.client.post(f'/cho/alerts/{alert.pk}/toggle/')
        self.assertRedirects(withdrawn, '/cho/alerts/')
        alert.refresh_from_db()
        self.assertFalse(alert.is_active)


class LguReadOnlyWorkflowTests(TestCase):
    def setUp(self):
        self.lgu = UserAccount.objects.create_user(
            username='planning_lgu', password='safe-password-123', role='LGU', account_status='APPROVED'
        )

    def test_lgu_analytics_and_map_pages_are_read_only(self):
        self.client.force_login(self.lgu)
        for url in (
            '/lgu-dashboard/',
            '/city-wide-monitoring/',
            '/lgu-hotspot-map/',
            '/lgu-risk-levels/',
            '/lgu/ai-predictions/',
            '/lgu-reports/',
            '/lgu-dengue-reports/',
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertEqual(self.client.post(url).status_code, 405)

    def test_lgu_cannot_use_cho_authority_pages(self):
        self.client.force_login(self.lgu)
        for url in ('/cho/alerts/', '/user-management/', '/cho/barangay-purok/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)


class ModelEvaluationTests(TestCase):
    def test_model_that_does_not_beat_persistence_is_marked_planning_support_only(self):
        summary = model_evaluation_summary({
            'mae': 1.3232,
            'rmse': 1.925,
            'persistence_baseline_mae': 1.1406,
            'persistence_baseline_rmse': 1.8,
        })

        self.assertTrue(summary['comparison_available'])
        self.assertFalse(summary['beats_baseline'])
        self.assertTrue(summary['planning_support_only'])
        self.assertEqual(summary['mae_difference'], 0.1826)
        self.assertIn('planning support only', summary['comparison_message'])

    def test_blood_type_training_policy_prohibits_individual_use(self):
        notice = BLOOD_TYPE_FEATURE_NOTICE.lower()
        self.assertIn('not used for an individual risk decision or diagnosis', notice)
        self.assertIn('de-identified historical barangay-month aggregate', notice)


class NotificationWorkflowTests(TestCase):
    def setUp(self):
        self.barangay = Barangay.objects.create(barangay_name='Saray')
        self.purok = Purok.objects.create(barangay=self.barangay, purok_name='Purok 1')
        self.cho = UserAccount.objects.create_user(
            username='notification_cho', password='safe-password-123', role='CHO', account_status='APPROVED'
        )
        self.resident = UserAccount.objects.create_user(
            username='notification_resident', password='safe-password-123', role='RESIDENT',
            account_status='APPROVED', assigned_barangay=self.barangay, assigned_purok=self.purok,
            email_verified=True,
        )
        self.bhw = UserAccount.objects.create_user(
            username='notification_bhw', password='safe-password-123', role='BHW', account_status='APPROVED'
        )
        self.chw = UserAccount.objects.create_user(
            username='notification_chw', password='safe-password-123', role='CHW', account_status='APPROVED'
        )

    def test_resident_submission_notifies_cho_and_mobile_inbox_marks_replies_read(self):
        token = self.client.post('/api/mobile/auth/login/', data=json.dumps({
            'email': 'notification_resident', 'password': 'safe-password-123',
        }), content_type='application/json').json()['token']
        response = self.client.post('/api/mobile/community-reports/', data=json.dumps({
            'barangay_id': self.barangay.pk, 'purok_id': self.purok.pk,
            'observation_type': 'Standing water', 'description': 'Water near the road.',
        }), content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(SystemNotification.objects.filter(recipient=self.cho, notification_type='REPORT').exists())

        report = CommunityReport.objects.get(pk=response.json()['id'])
        self.assertTrue(ReportAuditLog.objects.filter(
            community_report=report, actor=self.resident, action='CREATED'
        ).exists())
        report.status = 'FORWARDED'
        report.save(update_fields=['status'])
        self.client.force_login(self.cho)
        self.client.post(f'/cho/community-reports/{report.pk}/review/', {
            'status': 'VERIFIED', 'staff_response': 'CHO has scheduled a field visit.',
        })
        inbox = self.client.get('/api/mobile/notifications/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(inbox.status_code, 200)
        item = next(x for x in inbox.json()['notifications'] if x['type'] == 'REPLY')
        self.client.post('/api/mobile/notifications/', data=json.dumps({'ids': [item['id']]}),
                         content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertTrue(SystemNotification.objects.get(notification_id=item['id']).is_read)

    def test_cho_barangay_alert_notifies_only_residents_in_that_barangay(self):
        other_barangay = Barangay.objects.create(barangay_name='Dalipuga')
        other_resident = UserAccount.objects.create_user(
            username='other_alert_resident', password='safe-password-123',
            role='RESIDENT', account_status='APPROVED', assigned_barangay=other_barangay,
        )
        self.client.force_login(self.cho)
        response = self.client.post('/cho/alerts/create/', {
            'title': 'Remove standing water',
            'message': 'Please remove standing water around your home.',
            'risk_level': 'HIGH',
            'barangay_id': self.barangay.pk,
            'cho_review_confirmed': 'on',
            'cho_review_note': 'Reviewed verified reports and approved prevention guidance.',
        })

        self.assertRedirects(response, '/cho/alerts/')
        self.assertTrue(SystemNotification.objects.filter(
            recipient=self.resident, notification_type='ALERT',
            title='Remove standing water',
        ).exists())
        self.assertFalse(SystemNotification.objects.filter(
            recipient=other_resident, notification_type='ALERT',
        ).exists())

    def test_bhw_and_chw_receive_assignment_notifications(self):
        self.client.force_login(self.cho)
        for worker in (self.bhw, self.chw):
            response = self.client.post(f'/cho/bhw-assignments/{worker.pk}/assign/', {
                'barangay': self.barangay.pk, 'purok': self.purok.pk,
            })
            self.assertRedirects(response, '/cho/bhw-assignments/')
            worker.refresh_from_db()
            self.assertEqual(worker.assigned_barangay, self.barangay)
            self.assertTrue(SystemNotification.objects.filter(
                recipient=worker, notification_type='ASSIGNMENT'
            ).exists())
