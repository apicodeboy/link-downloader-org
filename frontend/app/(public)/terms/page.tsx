"use client";

import { Contact, LegalPage, mins } from "@/components/LegalPage";

export default function TermsPage() {
  return (
    <LegalPage title="Terms of use" updated="November 2026">
      {(site) => (
        <>
          <p>
            {site.site_name} is a free tool for saving copies of publicly available videos that you own or have
            permission to use. By using it you agree to these terms.
          </p>
          <h2>Acceptable use</h2>
          <ul>
            <li>Only download content you created, own, or have the rights holder&apos;s permission to use.</li>
            <li>Respect copyright and the terms of the platform the video comes from.</li>
            <li>Don&apos;t use the service to harass anyone, or to repost other people&apos;s work as your own.</li>
            <li>Don&apos;t try to get around the service&apos;s limits, or overload it with automated requests.</li>
          </ul>
          <h2>What the service won&apos;t do</h2>
          <p>
            It doesn&apos;t access private accounts or login-only, members-only, age-restricted, paywalled or
            DRM-protected content, and it never removes creators&apos; watermarks. Which sites work can change at
            any time.
          </p>
          <h2>Limits and storage</h2>
          <p>
            Videos up to {mins(site.guest_limits.max_duration_seconds)} minutes and {site.guest_limits.max_filesize_mb} MB.
            Files are deleted automatically {site.guest_limits.retention_minutes} minutes after they&apos;re created,
            so download what you need right away. We may limit or block use that harms the service or other
            people.
          </p>
          <h2>Copyright and takedown requests</h2>
          <p>
            Files aren&apos;t published or shared publicly. They are only available to the browser that requested
            them, for a short time. If you believe the service is being used to infringe your rights, contact{" "}
            <Contact site={site} /> with the link concerned, and we&apos;ll respond promptly.
          </p>
          <h2>No warranty</h2>
          <p>
            The service is provided as is, without any guarantee that it will be available, accurate or fit for a
            particular purpose. You are responsible for how you use downloaded content.
          </p>
          <h2>Changes</h2>
          <p>These terms may be updated. Continuing to use the service means you accept the current version.</p>
        </>
      )}
    </LegalPage>
  );
}
