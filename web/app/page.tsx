import Link from "next/link";

import { BrandMark, Wordmark } from "@/components/brand";
import { AndroidIcon } from "@/components/icons";
import { TraderHeroArt } from "@/components/trader-hero-art";
import styles from "./page.module.css";

/**
 * The public page.
 *
 * Written for the person it is for: a trader in a market who runs a shop on a notebook, WhatsApp and
 * memory. It should feel like it belongs in that market - warm, direct, a bit loud - rather than like
 * a software company explaining itself. What it says is what the product does: a sale and a receipt to
 * send, stock that matches the shelf, the day's money without the closing-time arithmetic, and a shop
 * link customers can open. WhatsApp stays where it is.
 */

const PROOF = ["Cash and transfer", "Receipts on WhatsApp", "Works offline", "Your boys can sign in"];

const CAPABILITIES = [
  {
    number: "01",
    title: "A sale, and a receipt to send",
    body: "Pick what the customer is buying, take the money, and the receipt is ready to send on WhatsApp. The customer keeps a link; you keep the record.",
  },
  {
    number: "02",
    title: "Stock that matches the shelf",
    body: "Every item in and out is written down as it happens, so the count is right. What is running out tells you before a customer asks for it.",
  },
  {
    number: "03",
    title: "The day's money, totalled",
    body: "Sales, spending and what is left, added up as you go. No closing-time arithmetic on the back of a notebook.",
  },
  {
    number: "04",
    title: "A shop link to share",
    body: "A public page with your products and prices, so a customer can look before they come - and get through to you on WhatsApp with one tap.",
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
        <div className={styles.heroText}>
          <p className={styles.eyebrow}>
            <span className={styles.eyebrowDot} aria-hidden />
            Built in Lagos for market traders
          </p>
          <h1 className={styles.headline}>
            Your shop,
            <br />
            in your pocket.
          </h1>
          <p className={styles.lede}>
            Sales, stock and money in one place - on the phone you already carry, and still there when
            the network drops. Keep your WhatsApp exactly as it is.
          </p>
          <div className={styles.actions}>
            <Link className={styles.primaryCta} href="/start?intent=create">
              Open your shop
            </Link>
            <a
              className={styles.androidCta}
              href="https://github.com/Ksschkw/AHIA/releases/latest/download/AHIA-latest.apk"
              download="AHIA-latest.apk"
              rel="noopener noreferrer"
            >
              <AndroidIcon size={20} />
              <span>Install for Android</span>
            </a>
            <Link className={styles.quietCta} href="/start">
              I already have an account
            </Link>
          </div>
          <ul className={styles.proof}>
            {PROOF.map((item) => (
              <li key={item} className={styles.proofItem}>
                {item}
              </li>
            ))}
          </ul>
        </div>

        <TraderHeroArt />
      </section>

      <section className={styles.capabilities}>
        {CAPABILITIES.map((capability) => (
          <article key={capability.number} className={styles.capability}>
            <span className={styles.capabilityNumber}>{capability.number}</span>
            <h2 className={styles.capabilityTitle}>{capability.title}</h2>
            <p className={styles.capabilityBody}>{capability.body}</p>
          </article>
        ))}
      </section>

      <section className={styles.closing}>
        <h2 className={styles.closingTitle}>Opening takes a minute</h2>
        <p className={styles.closingBody}>
          A name for the business, the things you sell, and you are recording sales. Bring in your
          salespeople when you are ready - each one signs in with what they are allowed to do.
        </p>
        <Link className={styles.primaryCta} href="/start?intent=create">
          Open your shop
        </Link>
        <p className={styles.closingNote}>Nothing to install to look around.</p>
      </section>

      <footer className={styles.footer}>
        <Wordmark />
        <span className={styles.footerNote}>
          One business or ten, one trader or a whole shop floor.
        </span>
      </footer>
    </main>
  );
}
