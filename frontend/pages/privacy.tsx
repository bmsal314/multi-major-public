import Head from "next/head";
export default function Privacy() {
  return (
    <>
      <Head>
        <title>Privacy & planning notice · Multi-Major</title>
      </Head>
      <main className="policy-page">
        <a className="platform-brand" href="/">
          Multi-Major
        </a>
        <h1>
          Your information.
          <br />
          Your plan.
        </h1>
        <p className="lede">
          Multi-Major is an independent student planning tool. It is not
          affiliated with or endorsed by any university.
        </p>
        <h2>What your account remembers</h2>
        <p>
          With your permission, we store parsed academic requirements, relevant
          transcript courses and grades, audit evidence, saved semester maps,
          preferences and your edits. We remove identifying audit headers and do
          not intentionally retain student names or student IDs from PDFs. Your
          verified email identifies your account.
        </p>
        <h2>What happens to your PDFs</h2>
        <p>
          Reports upload to private storage for processing. Originals are
          deleted after processing succeeds or fails. Incomplete uploads expire
          within 24 hours. Cleanup failures are retried and monitored; a service
          outage may delay deletion. There is no shared PDF library.
        </p>
        <h2>Who can access your data</h2>
        <p>
          Other students cannot access your account records. Authorized
          processing and maintenance services need access to operate the
          application. The hosting providers are Vercel and Supabase; account
          emails are delivered through the configured email provider. We do not
          send your audits to an AI model, sell them, or use them for
          advertising.
        </p>
        <h2>Export and deletion</h2>
        <p>
          Account settings let you export your data, delete plans, delete parsed
          audits and their associated maps, or delete your account. Deletion
          removes active records and queued processing. Provider backups can
          retain earlier records until their configured retention period ends.
          The deployed service’s actual retention period and support contact
          must be published before the pilot opens.
        </p>
        <h2>A draft, not an official degree audit</h2>
        <p>
          DARS reports do not describe every prerequisite, course offering or
          double-counting policy. Interpretations can be incomplete. Review
          program identities, catalog years, unknown sections, credit estimates
          and advisor decisions. Confirm your final schedule and graduation
          eligibility with your academic advisor.
        </p>
        <h2>Pre-med planning</h2>
        <p>
          Pre-med tracking is optional. Medical schools set their own
          requirements and may treat transfer, examination and online credit
          differently. The checklist is not a guarantee of admission
          eligibility.
        </p>
        <p className="small">
          Pilot policy · August 28, 2026 · Institutional procurement, privacy
          review and accessibility assessment are required before any
          institution-wide deployment.
        </p>
        <a href="/">← Back to Multi-Major</a>
      </main>
    </>
  );
}

// Per-request rendering supplies a fresh script nonce; no shared HTML cache.
export async function getServerSideProps() {
  return { props: {} };
}
