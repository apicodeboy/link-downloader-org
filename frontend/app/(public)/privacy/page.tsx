"use client";

import { Contact, LegalPage } from "@/components/LegalPage";

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy" updated="November 2026">
      {(site) => (
        <>
          <p>{site.site_name} collects as little as it can. There are no accounts, ads or third-party trackers.</p>
          <h2>What is stored</h2>
          <ul>
            <li>
              <strong>One cookie</strong> with a random ID, so your files and history stay private to your browser.
              It&apos;s required for the site to work. It lasts {site.history_days} days and isn&apos;t used for
              tracking.
            </li>
            <li>
              <strong>The links you submit</strong>, the details of each video, and your list of past downloads, kept
              for as long as your browser&apos;s ID lasts.
            </li>
            <li>
              <strong>Video files</strong> you download or edit, deleted automatically after{" "}
              {site.guest_limits.retention_minutes} minutes. Watermark images you upload are kept until you delete
              them.
            </li>
            <li>
              <strong>Security logs</strong>: your IP address, browser type and the action taken. They are used to
              prevent abuse and are deleted after {site.log_retention_days} days.
            </li>
          </ul>
          <h2>Who sees it</h2>
          <p>
            Only the site operator. Nothing is sold or shared. When you request a video, our server contacts the
            platform it&apos;s on. The platform sees our server, not you.
          </p>
          <h2>Your choices</h2>
          <p>
            You can delete any file from My files at any time. Clearing this site&apos;s cookies removes your
            access to your history; the remaining data is then deleted automatically. For anything else, contact{" "}
            <Contact site={site} />.
          </p>
        </>
      )}
    </LegalPage>
  );
}
