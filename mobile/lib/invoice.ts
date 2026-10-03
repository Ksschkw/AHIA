import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { type CustomerList, type TenantDetails } from "@/lib/api";

function formatMoney(amount: string | null | undefined): string {
  if (!amount) return "Price on request";
  const num = Number(amount);
  if (!Number.isFinite(num)) return `NGN ${amount}`;
  return `NGN ${num.toLocaleString("en-NG", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

export function buildInvoiceHtml(
  business: { name: string; slug?: string },
  details: TenantDetails | null,
  list: CustomerList
): string {
  const dateStr = new Date(list.created_at).toLocaleDateString("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const invoiceNumber = `INV-${list.id.slice(0, 8).toUpperCase()}`;
  const customerName = list.customer_name || "Valued Customer";
  const customerPhone = list.customer_phone || "N/A";
  const businessPhone = details?.phone || "";
  const fulfillmentLabel = list.fulfillment_type === "waybill" ? "Waybill / Delivery" : "In-Shop Pickup";

  let computedSubtotal = 0;
  const rowsHtml = list.lines
    .map((line, idx) => {
      const name = line.product_name || line.free_text || "Item";
      const qty = Number(line.quantity) || 1;
      const unitPriceNum = Number(line.shop_price ?? "0");
      const hasPrice = Boolean(line.shop_price && Number.isFinite(unitPriceNum));
      const lineTotal = hasPrice ? unitPriceNum * qty : 0;
      if (hasPrice) computedSubtotal += lineTotal;

      const stateBadge =
        line.state === "have_it"
          ? `<span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">GOTTEN</span>`
          : line.state === "buy_it"
          ? `<span style="background:#fef9c3;color:#a16207;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">IN MARKET</span>`
          : line.state === "cannot_get"
          ? `<span style="background:#fee2e2;color:#b91c1c;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">UNAVAILABLE</span>`
          : `<span style="background:#f1f5f9;color:#64748b;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">PENDING</span>`;

      return `
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 10px 8px; text-align: center; color: #64748b; font-size: 13px;">${idx + 1}</td>
          <td style="padding: 10px 8px;">
            <div style="font-weight: 600; color: #0f172a; font-size: 14px;">${name}</div>
            ${line.group_name ? `<div style="font-size: 11px; color: #94a3b8;">${line.group_name}</div>` : ""}
          </td>
          <td style="padding: 10px 8px; text-align: center; font-size: 14px; font-weight: 600;">${line.quantity}</td>
          <td style="padding: 10px 8px; text-align: right; font-size: 14px;">
            ${hasPrice ? formatMoney(line.shop_price) : `<span style="color:#94a3b8;font-style:italic;">Pending</span>`}
          </td>
          <td style="padding: 10px 8px; text-align: right; font-size: 14px; font-weight: 700; color: #0f172a;">
            ${hasPrice ? formatMoney(lineTotal.toString()) : `<span style="color:#94a3b8;">-</span>`}
          </td>
          <td style="padding: 10px 8px; text-align: center;">${stateBadge}</td>
        </tr>
      `;
    })
    .join("");

  const grandTotal = list.priced_total ? formatMoney(list.priced_total) : formatMoney(computedSubtotal.toString());
  const dispatchFee = list.dispatch_cost ? formatMoney(list.dispatch_cost) : null;

  const totalNum = (Number(list.priced_total) || computedSubtotal) + (Number(list.dispatch_cost) || 0);
  const amountPaidNum = Number(list.amount_paid ?? list.advance_payment ?? "0");
  const balanceRemaining = Math.max(0, totalNum - amountPaidNum);

  const waybillSection = list.waybill_number
    ? `
      <div style="margin-top: 24px; padding: 16px; background: #f8fafc; border-radius: 8px; border: 1px dashed #cbd5e1;">
        <div style="font-weight: 700; color: #084a2f; font-size: 13px; text-transform: uppercase; margin-bottom: 8px;">
          Waybill & Logistics Tracking
        </div>
        <div style="font-size: 13px; color: #334155; line-height: 1.6;">
          <div><strong>Courier / Transporter:</strong> ${list.transporter_name || "Courier"}</div>
          <div><strong>Waybill Number:</strong> #${list.waybill_number}</div>
          ${list.transporter_phone ? `<div><strong>Transporter Phone:</strong> ${list.transporter_phone}</div>` : ""}
          ${list.tracking_url ? `<div><strong>Tracking Link:</strong> <a href="${list.tracking_url}" style="color:#084a2f;">${list.tracking_url}</a></div>` : ""}
        </div>
      </div>
    `
    : "";

  return `
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8">
        <title>${invoiceNumber} - ${business.name}</title>
        <style>
          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 36px 28px;
            color: #0f172a;
            background: #ffffff;
          }
          .header-row {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid #084a2f;
            padding-bottom: 20px;
            margin-bottom: 24px;
          }
          .biz-name {
            font-size: 26px;
            font-weight: 800;
            color: #084a2f;
            letter-spacing: -0.5px;
          }
          .biz-meta {
            font-size: 13px;
            color: #64748b;
            margin-top: 4px;
          }
          .invoice-tag {
            text-align: right;
          }
          .invoice-title {
            font-size: 22px;
            font-weight: 800;
            color: #0f172a;
          }
          .invoice-sub {
            font-size: 13px;
            color: #64748b;
            margin-top: 4px;
          }
          .client-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
          }
          .client-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            color: #94a3b8;
            letter-spacing: 0.5px;
          }
          .client-name {
            font-size: 16px;
            font-weight: 700;
            color: #0f172a;
            margin-top: 4px;
          }
          .client-contact {
            font-size: 13px;
            color: #475569;
            margin-top: 2px;
          }
          table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
          }
          th {
            background: #084a2f;
            color: #ffffff;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 10px 8px;
          }
          .totals-wrap {
            display: flex;
            justify-content: flex-end;
            margin-top: 16px;
          }
          .totals-table {
            width: 320px;
            border-collapse: collapse;
          }
          .totals-table td {
            padding: 6px 8px;
            font-size: 14px;
          }
          .grand-total {
            font-size: 18px;
            font-weight: 800;
            color: #084a2f;
            border-top: 2px solid #084a2f;
            padding-top: 10px !important;
          }
          .paid-row {
            color: #15803d;
            font-weight: 700;
          }
          .balance-row {
            color: #b91c1c;
            font-weight: 800;
            border-top: 1px dashed #cbd5e1;
            padding-top: 8px !important;
          }
          .footer {
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid #e2e8f0;
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
          }
        </style>
      </head>
      <body>
        <div class="header-row">
          <div>
            <div class="biz-name">${business.name}</div>
            <div class="biz-meta">${businessPhone ? `Phone: ${businessPhone}` : "Official Merchant Invoice"}</div>
          </div>
          <div class="invoice-tag">
            <div class="invoice-title">INVOICE</div>
            <div class="invoice-sub">${invoiceNumber}</div>
            <div class="invoice-sub">Date: ${dateStr}</div>
          </div>
        </div>

        <div class="client-box">
          <div>
            <div class="client-label">Billed To</div>
            <div class="client-name">${customerName}</div>
            <div class="client-contact">Phone: ${customerPhone}</div>
          </div>
          <div style="text-align: right;">
            <div class="client-label">Fulfillment & Status</div>
            <div style="margin-top: 4px;">
              <span style="background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; text-transform: uppercase; margin-right: 4px;">
                ${fulfillmentLabel}
              </span>
              <span style="background: ${list.status === "confirmed" ? "#dcfce7" : "#fef9c3"}; color: ${list.status === "confirmed" ? "#15803d" : "#a16207"}; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; text-transform: uppercase;">
                ${list.status}
              </span>
            </div>
          </div>
        </div>

        <table>
          <thead>
            <tr>
              <th style="width: 36px; text-align: center;">#</th>
              <th style="text-align: left;">Item Description</th>
              <th style="width: 50px; text-align: center;">Qty</th>
              <th style="width: 110px; text-align: right;">Unit Price</th>
              <th style="width: 120px; text-align: right;">Total</th>
              <th style="width: 90px; text-align: center;">Status</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>

        <div class="totals-wrap">
          <table class="totals-table">
            <tr>
              <td style="color: #64748b;">Subtotal</td>
              <td style="text-align: right; font-weight: 600;">${formatMoney(computedSubtotal.toString())}</td>
            </tr>
            ${
              dispatchFee
                ? `<tr>
                    <td style="color: #64748b;">Waybill / Dispatch</td>
                    <td style="text-align: right; font-weight: 600;">${dispatchFee}</td>
                  </tr>`
                : ""
            }
            <tr>
              <td class="grand-total">Total Order</td>
              <td class="grand-total" style="text-align: right;">${grandTotal}</td>
            </tr>
            ${
              amountPaidNum > 0
                ? `
                <tr>
                  <td class="paid-row">Paid / Advance Deposit</td>
                  <td class="paid-row" style="text-align: right;">- ${formatMoney(amountPaidNum.toString())}</td>
                </tr>
                <tr>
                  <td class="balance-row">Balance Due</td>
                  <td class="balance-row" style="text-align: right;">${formatMoney(balanceRemaining.toString())}</td>
                </tr>
                `
                : ""
            }
          </table>
        </div>

        ${waybillSection}

        <div class="footer">
          <p style="margin: 0; font-weight: 600; color: #475569;">Thank you for your business!</p>
          <p style="margin: 4px 0 0 0;">Generated with AHIA - Nigerian Commerce System</p>
        </div>
      </body>
    </html>
  `;
}

export async function generateAndSharePdfInvoice(
  business: { name: string; slug?: string },
  details: TenantDetails | null,
  list: CustomerList
): Promise<void> {
  const html = buildInvoiceHtml(business, details, list);
  const customerName = list.customer_name || "Customer";

  const { uri } = await Print.printToFileAsync({
    html,
    base64: false,
  });

  const isAvailable = await Sharing.isAvailableAsync();
  if (isAvailable) {
    await Sharing.shareAsync(uri, {
      UTI: "com.adobe.pdf",
      mimeType: "application/pdf",
      dialogTitle: `Share Invoice - ${customerName}`,
    });
  } else {
    await Print.printAsync({ html });
  }
}

export async function printInvoice(
  business: { name: string; slug?: string },
  details: TenantDetails | null,
  list: CustomerList
): Promise<void> {
  const html = buildInvoiceHtml(business, details, list);
  await Print.printAsync({ html });
}
