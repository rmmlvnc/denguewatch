from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Approve one specifically named CHO account after interactive confirmation. "
        "Use for initial setup or local account recovery."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="Username of the CHO account to bootstrap")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"].strip()

        try:
            account = User.objects.select_for_update().get(username__iexact=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"No account found for username '{username}'.") from exc

        if account.role != "CHO":
            raise CommandError("The selected account is not a CHO account; no changes were made.")

        self.stdout.write(
            "Selected CHO account:\n"
            f"  Username: {account.username}\n"
            f"  Email: {account.email or '(none)'}\n"
            f"  Current status: {account.account_status}\n"
            "This will mark the email verified and enable CHO access."
        )
        confirmation = input("Type APPROVE to continue: ").strip()
        if confirmation != "APPROVE":
            raise CommandError("Approval cancelled; no changes were made.")

        account.email_verified = True
        account.account_status = "APPROVED"
        account.is_active = True
        account.save(update_fields=["email_verified", "account_status", "is_active"])

        self.stdout.write(
            self.style.SUCCESS(
                f"CHO account '{account.username}' is verified and approved. "
                "Sign in with its username/email and password."
            )
        )
