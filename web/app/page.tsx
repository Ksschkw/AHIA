import Link from "next/link";

import { BrandMark, Wordmark } from "@/components/brand";
import styles from "./page.module.css";

/**
 * The public page.
 *
 * Written for the person it is for: a trader in a market who runs a shop on a notebook, WhatsApp and
 * memory. It says what AHIA does in their words - a sale and a receipt, stock that matches the shelf,
 * the day's money - and it does not pretend to replace WhatsApp, because it does not.
 *
 * A server component with no data fetching: nothing about this page can be slow, and nothing about it
 * depends on the API being reachable.
 */

const CAPABILITIES = [
  {
    title: "A sale, and a receipt to send",
    body: "Record what you sold, take cash or a transfer, and share the receipt on WhatsApp. The customer keeps a link; you keep the record.",
  },
  {
    title: "Stock that matches the shelf",
    body: "Every item in and out is written down as it happens, so the count is right - and what is running out tells you before a customer asks.",
  },
  {
    title: "The day's money, without a notebook",
    body: "Takings, spending and what is left, totalled as you go. No closing-time arithmetic, and no guessing whether today was a good day.",
  },
];

export default function Landing() {
  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <span className={styles.brand}>
          <BrandMark size={34} />
          <Wordmark />
        </span>
        <nav className={styles.nav}>
          <Link className={styles.navLink} href="/start">
            Sign in
          </Link>
          <Link className={styles.navCta} href="/start?intent=create">
            Open your shop
          </Link>
        </nav>
      </header>

      <section className={styles.hero}>
        <p className={styles.eyebrow}>Built for market traders</p>
        <h1 className={styles.headline}>Keep your shop in your pocket.</h1>
        <p className={styles.lede}>
          Sales, stock and money in one place - on the phone you already carry, and still there when
          the network drops. Your WhatsApp stays exactly where it is.
        </p>
        <div className={styles.actions}>
          <Link className={styles.primaryCta} href="/start?intent=create">
            Open your shop
          </Link>
          <Link className={styles.quietCta} href="/start">
            I already have an account
          </Link>
        </div>
        <p className={styles.note}>Works offline. Nothing to install to look around.</p>
      </section>

      <section className={styles.capabilities}>
        {CAPABILITIES.map((capability) => (
          <article key={capability.title} className={styles.capability}>
            <h2 className={styles.capabilityTitle}>{capability.title}</h2>
            <p className={styles.capabilityBody}>{capability.body}</p>
          </article>
        ))}
      </section>

      <section className={styles.closing}>
        <h2 className={styles.closingTitle}>Opening takes a minute</h2>
        <p className={styles.closingBody}>
          A name for the business, the things you sell, and you are recording sales. Invite the boys
          in the shop when you are ready.
        </p>
        <Link className={styles.primaryCta} href="/start?intent=create">
          Open your shop
        </Link>
      </section>

      <footer className={styles.footer}>
        <Wordmark />
        <span className={styles.footerNote}>
          Cash and transfer, receipts you can share, and a shop link customers can open.
        </span>
      </footer>
    </main>
  );
}
