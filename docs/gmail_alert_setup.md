# Gmail delivery for CHO resident alerts

The Django website continues to create in-app notifications. When SMTP is configured, publishing an alert also sends an email to each matching approved resident who has an email address on their account.

Resident addresses must be verified before they receive alert emails. Registration sends a separate 24-hour verification link; the resident can also request a resend from **Mobile app → Profile**. Changing the account email clears verification and sends a new verification link. In-app notifications remain available while email is unverified. Existing resident accounts start unverified after the database migration and need to verify from their profile before receiving email alerts.

## Configure a Gmail sender

1. Use a dedicated Gmail account controlled by the project team. Complete Google's account verification and turn on 2-Step Verification.
2. Create a Google **App Password** for this Django project. Use the App Password, not the account's normal password. Google may not offer App Passwords for accounts with certain security policies.
3. Copy `.env.example` to `.env` in the `PRE-SYSTEM` folder and set:

   ```dotenv
   EMAIL_HOST_USER=your-project-sender@gmail.com
   EMAIL_HOST_PASSWORD=your-16-character-app-password
   DEFAULT_FROM_EMAIL=your-project-sender@gmail.com
   ```

   Keep `.env` private; it is excluded from Git. Do not put these values in the React Native project.
4. Restart Django. Publish a test alert for a test resident account whose email address you can access. Check the inbox and spam folder.

If Gmail is not configured, Django keeps the in-app notification and writes the email to the Django console instead. The CHO page reports that console mode is active.

## Mobile alert link

The email button uses `denguewatch://alert/<id>`. Expo Router opens the matching alert page, which requests the alert from Django and checks that it is still active and is available to the signed-in resident's barangay. If the resident is signed out, they are sent to sign-in and returned to the alert after login.

The verification email uses `denguewatch://verify-email/<signed-token>`. The token expires after 24 hours and is bound to the resident's current email. Verification opens a confirmation page in the mobile app; expired links can be resent from Profile.

For a local Expo Go demonstration, Expo Go cannot use the app's custom `denguewatch://` scheme. Temporarily set the two link bases in `.env` to the computer's current LAN IP and Metro port (the address shown by `npx expo start`), for example:

```dotenv
MOBILE_VERIFICATION_LINK_BASE=exp://192.168.1.20:8081/--/verify-email
MOBILE_ALERT_LINK_BASE=exp://192.168.1.20:8081/--/alert
```

Replace `192.168.1.20` with the current computer IP, keep Metro running, and keep the phone on the same Wi-Fi. These development URLs change with the network and should not be used for production. For a release, restore the `denguewatch://` schemes and create an installed app build; HTTPS App Links and a website fallback require a deployed domain.

This custom scheme works with an installed DengueWatch development or production build. Expo Go's QR code is for development and does not provide a stable public email link. A public HTTPS link that opens the installed app and falls back to a website requires a deployed domain and Android App Links/iOS Universal Links configuration; the project does not yet have that domain configured.
