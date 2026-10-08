import { DoubleCheckIcon } from "./icons";
import styles from "./trader-hero-art.module.css";

const NAIRA = "\u20A6";

export function TraderHeroArt() {
  return (
    <div className={styles.artContainer} aria-hidden>
      {/* Floor ambient blur shadow */}
      <div className={styles.ambientShadow} />

      {/* WhatsApp Live Order Bubble (Top Right Layer) */}
      <div className={styles.whatsappCard}>
        <div className={styles.whatsappHeader}>
          <div className={styles.whatsappIconCircle}>WA</div>
          <span className={styles.whatsappSender}>Chidi (Onitsha Customer)</span>
        </div>
        <p className={styles.whatsappText}>
          &ldquo;Oga Kene, 50pcs Hot 8 21D Glass + 20pcs 65W GaN Charger received. Balance paid!&rdquo;
        </p>
        <div className={styles.whatsappMeta}>
          <span>PAID: {NAIRA}96,500.00</span>
          <span className={styles.whatsappTicks}>
            <DoubleCheckIcon size={14} />
            <span>10:42 AM</span>
          </span>
        </div>
      </div>

      {/* Main Isometric Market Stall Model Card */}
      <div className={styles.stallCard}>
        <div className={styles.stallHeader}>
          <div className={styles.stallInfo}>
            <span className={styles.stallMarket}>Alaba Int&apos;l Market &bull; Line 4, Shop B12</span>
            <span className={styles.stallName}>Kene &amp; Sons Electronics Ltd</span>
          </div>
          <span className={styles.statusPill}>
            <span className={styles.statusDot} />
            Open
          </span>
        </div>

        {/* 3D Isometric Vector Stage */}
        <div className={styles.vectorStage}>
          <svg
            className={styles.vectorSvg}
            viewBox="0 0 240 160"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <linearGradient id="canopyGreen" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#10b981" />
                <stop offset="100%" stopColor="#064e3b" />
              </linearGradient>
              <linearGradient id="canopyGold" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#fbbf24" />
                <stop offset="100%" stopColor="#d97706" />
              </linearGradient>
              <linearGradient id="stallBase" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#1e293b" />
                <stop offset="100%" stopColor="#0f172a" />
              </linearGradient>
              <linearGradient id="counterSurface" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#475569" />
                <stop offset="100%" stopColor="#1e293b" />
              </linearGradient>
            </defs>

            {/* Counter Base 3D Body */}
            <path d="M40 85 L200 85 L215 145 L25 145 Z" fill="url(#stallBase)" stroke="#334155" strokeWidth="2" />

            {/* Top Shelf Counter Surface */}
            <path d="M22 85 L218 85 L200 100 L40 100 Z" fill="url(#counterSurface)" stroke="#475569" strokeWidth="1.5" />

            {/* Front Panel Accents */}
            <rect x="50" y="110" width="140" height="26" rx="6" fill="#0f172a" />
            <rect x="60" y="115" width="34" height="16" rx="4" fill="#059669" opacity="0.8" />
            <rect x="104" y="115" width="34" height="16" rx="4" fill="#0284c7" opacity="0.8" />
            <rect x="148" y="115" width="32" height="16" rx="4" fill="#d97706" opacity="0.8" />

            {/* Isometric Canopy Roof */}
            <g>
              {/* Stripe 1 */}
              <path d="M25 45 L55 15 L78 45 Z" fill="url(#canopyGreen)" />
              {/* Stripe 2 */}
              <path d="M55 15 L85 15 L102 45 L78 45 Z" fill="url(#canopyGold)" />
              {/* Stripe 3 */}
              <path d="M85 15 L115 15 L124 45 L102 45 Z" fill="url(#canopyGreen)" />
              {/* Stripe 4 */}
              <path d="M115 15 L145 15 L146 45 L124 45 Z" fill="url(#canopyGold)" />
              {/* Stripe 5 */}
              <path d="M145 15 L175 15 L168 45 L146 45 Z" fill="url(#canopyGreen)" />
              {/* Stripe 6 */}
              <path d="M175 15 L215 45 L168 45 Z" fill="url(#canopyGold)" />

              {/* Scalloped Valance Trim */}
              <path
                d="M25 45 Q40 55 55 45 Q70 55 85 45 Q100 55 115 45 Q130 55 145 45 Q160 55 175 45 Q195 55 215 45"
                fill="none"
                stroke="#fbbf24"
                strokeWidth="2.5"
              />
            </g>

            {/* Canopy Steel Support Pillars */}
            <rect x="42" y="45" width="4" height="40" fill="#94a3b8" />
            <rect x="194" y="45" width="4" height="40" fill="#94a3b8" />

            {/* Smartphone & POS Terminal Screen */}
            <rect x="100" y="65" width="40" height="24" rx="4" fill="#1e293b" stroke="#38bdf8" strokeWidth="1.5" />
            <rect x="106" y="69" width="28" height="12" rx="2" fill="#0ea5e9" opacity="0.9" />
            <circle cx="120" cy="85" r="2" fill="#4ade80" />
          </svg>

          {/* Floating 3D Gold Naira Coin */}
          <div className={styles.floatingCoin}>
            <svg width="42" height="42" viewBox="0 0 42 42">
              <defs>
                <linearGradient id="coinGold" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#fef08a" />
                  <stop offset="50%" stopColor="#f59e0b" />
                  <stop offset="100%" stopColor="#b45309" />
                </linearGradient>
              </defs>
              <circle cx="21" cy="21" r="19" fill="url(#coinGold)" stroke="#fef3c7" strokeWidth="2" />
              <circle cx="21" cy="21" r="14" fill="none" stroke="#d97706" strokeWidth="1.5" />
              <text
                x="21"
                y="27"
                textAnchor="middle"
                fill="#ffffff"
                fontSize="18"
                fontWeight="900"
                fontFamily="sans-serif"
              >
                {NAIRA}
              </text>
            </svg>
          </div>
        </div>

        {/* Live Shelf Goods */}
        <div className={styles.itemsRow}>
          <div className={styles.itemChip}>
            <span className={styles.itemTitle}>Hot 8 21D King Glass</span>
            <span className={styles.itemPrice}>{NAIRA}1,500</span>
          </div>
          <div className={styles.itemChip}>
            <span className={styles.itemTitle}>65W GaN Fast Charger</span>
            <span className={styles.itemPrice}>{NAIRA}12,500</span>
          </div>
        </div>
      </div>

      {/* Physical Waybill Bus Park Dispatch Slip (Bottom Left Layer) */}
      <div className={styles.waybillCard}>
        <div className={styles.waybillKicker}>
          <span>PARK WAYBILL SLIP</span>
          <span>WB-9041</span>
        </div>
        <div className={styles.waybillRoute}>Lagos &rarr; Onitsha (Upper Iweka)</div>
        <div className={styles.waybillCarrier}>Ezenwata Transport &bull; Night Express</div>
        <div className={styles.waybillItems}>4 Cartons &bull; Screenguards &amp; Chargers</div>
        <div className={styles.waybillStamp}>WAYBILLED</div>
      </div>

      {/* Offline SQLite Ledger Pill (Bottom Right Layer) */}
      <div className={styles.ledgerPill}>
        <span className={styles.statusDot} />
        <div>
          <span className={styles.ledgerLabel}>Today&apos;s Gross Sales</span>
          <div className={styles.ledgerAmount}>{NAIRA}220,900.00</div>
        </div>
      </div>
    </div>
  );
}
