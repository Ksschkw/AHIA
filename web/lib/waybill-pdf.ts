/**
 * Multi-page PDF Waybill Generator for Nigerian Market Orders.
 *
 * Built with zero external dependencies to generate standard, valid PDF-1.4 documents
 * that can be downloaded, printed, or sent directly to transporters, waybill drivers,
 * and market dispatchers.
 */

export interface WaybillItem {
  text: string;
  quantity: number;
  price?: string | null;
  categoryPath?: string[];
}

export interface WaybillSection {
  title: string;
  subsections?: {
    subtitle: string;
    items: WaybillItem[];
  }[];
  items?: WaybillItem[];
}

export interface WaybillDocument {
  shopName: string;
  customerName: string;
  customerPhone: string;
  date: string;
  includePrices: boolean;
  totalPrice?: string | null;
  sections: WaybillSection[];
}

function escapePdfText(text: string): string {
  return text
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)")
    .replace(/[^\x20-\x7E]/g, "?");
}

export function generateWaybillPdfBlob(doc: WaybillDocument): Blob {
  const pageWidth = 595.28; // A4 width in pt
  const pageHeight = 841.89; // A4 height in pt
  const margin = 40;
  const contentWidth = pageWidth - margin * 2;

  // Flatten items into printable lines to handle multi-page layout accurately
  type PrintLine =
    | { type: "rootHeader"; text: string }
    | { type: "subHeader"; text: string }
    | { type: "item"; text: string; quantity: number; price?: string | null }
    | { type: "divider" };

  const lines: PrintLine[] = [];

  for (const sec of doc.sections) {
    lines.push({ type: "rootHeader", text: sec.title });
    if (sec.items && sec.items.length > 0) {
      for (const it of sec.items) {
        lines.push({ type: "item", text: it.text, quantity: it.quantity, price: it.price });
      }
    }
    if (sec.subsections) {
      for (const sub of sec.subsections) {
        lines.push({ type: "subHeader", text: sub.subtitle });
        for (const it of sub.items) {
          lines.push({ type: "item", text: it.text, quantity: it.quantity, price: it.price });
        }
      }
    }
  }

  // Break lines into pages
  const pages: PrintLine[][] = [];
  let currentPage: PrintLine[] = [];
  let currentY = 160; // Start after header
  const maxY = pageHeight - 60; // Leave margin for footer

  for (const line of lines) {
    let lineHeight = 20;
    if (line.type === "rootHeader") lineHeight = 32;
    else if (line.type === "subHeader") lineHeight = 24;

    if (currentY + lineHeight > maxY) {
      pages.push(currentPage);
      currentPage = [];
      currentY = 80; // Subsequent pages have smaller top margin
    }
    currentPage.push(line);
    currentY += lineHeight;
  }
  if (currentPage.length > 0 || pages.length === 0) {
    pages.push(currentPage);
  }

  const totalPages = pages.length;

  // Build PDF Objects
  const pdfObjects: string[] = [];
  const objectOffsets: number[] = [];

  const addObject = (content: string): number => {
    pdfObjects.push(content);
    return pdfObjects.length;
  };

  // Object 1: Catalog
  addObject("<< /Type /Catalog /Pages 2 0 R >>");

  // Object 2: Pages list (will update Kids after page objects are created)
  const pagesObjIndex = 2;
  pdfObjects.push(""); // Placeholder for Object 2

  // Fonts
  const fontRegularObj = addObject("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  const fontBoldObj = addObject("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>");

  const pageObjectIds: number[] = [];

  pages.forEach((pageLines, pageIndex) => {
    const isFirstPage = pageIndex === 0;
    const pageNum = pageIndex + 1;

    let stream = "";
    // Background / Header decor
    if (isFirstPage) {
      // Top header banner
      stream += "0.031 0.290 0.184 rg\n"; // Forest Green #084a2f
      stream += `0 ${pageHeight - 80} ${pageWidth} 80 re f\n`;

      // Header Text
      stream += "BT\n";
      stream += "/F2 20 Tf\n";
      stream += "1 1 1 rg\n"; // White text
      stream += `${margin} ${pageHeight - 42} Td\n`;
      stream += `(${escapePdfText(doc.shopName)}) Tj\n`;
      stream += "ET\n";

      stream += "BT\n";
      stream += "/F1 11 Tf\n";
      stream += "0.9 0.95 0.92 rg\n";
      stream += `${margin} ${pageHeight - 62} Td\n`;
      stream += `(${escapePdfText("MARKET WAYBILL & ORDER LIST")}) Tj\n`;
      stream += "ET\n";

      // Customer Info Box
      stream += "0.96 0.96 0.96 rg\n";
      stream += `${margin} ${pageHeight - 145} ${contentWidth} 50 re f\n`;
      stream += "0.85 0.85 0.85 RG 1 w\n";
      stream += `${margin} ${pageHeight - 145} ${contentWidth} 50 re S\n`;

      stream += "BT\n";
      stream += "/F2 11 Tf 0.1 0.1 0.1 rg\n";
      stream += `${margin + 12} ${pageHeight - 114} Td\n`;
      stream += `(Customer: ${escapePdfText(doc.customerName || "Customer")}) Tj\n`;
      stream += "/F1 11 Tf 0.3 0.3 0.3 rg\n";
      stream += `160 0 Td (Phone: ${escapePdfText(doc.customerPhone)}) Tj\n`;
      stream += `160 0 Td (Date: ${escapePdfText(doc.date)}) Tj\n`;
      stream += "ET\n";

      stream += "BT\n";
      stream += "/F1 10 Tf 0.4 0.4 0.4 rg\n";
      stream += `${margin + 12} ${pageHeight - 134} Td\n`;
      if (doc.includePrices && doc.totalPrice) {
        stream += `(Mode: Catalog Prices Included | Estimated Total: ${escapePdfText(doc.totalPrice)}) Tj\n`;
      } else {
        stream += `(Mode: Market Trust Waybill | Prices Quoted Upon Packing & Dispatch) Tj\n`;
      }
      stream += "ET\n";
    } else {
      // Subsequent page mini header
      stream += "0.031 0.290 0.184 rg\n";
      stream += `0 ${pageHeight - 35} ${pageWidth} 35 re f\n`;

      stream += "BT\n";
      stream += "/F2 11 Tf 1 1 1 rg\n";
      stream += `${margin} ${pageHeight - 24} Td\n`;
      stream += `(${escapePdfText(doc.shopName)} - Market Waybill (cont.)) Tj\n`;
      stream += "ET\n";
    }

    // Render lines for this page
    let yPos = isFirstPage ? pageHeight - 170 : pageHeight - 65;

    for (const item of pageLines) {
      if (item.type === "rootHeader") {
        yPos -= 26;
        // Category Root Box
        stream += "0.93 0.96 0.94 rg\n";
        stream += `${margin} ${yPos - 5} ${contentWidth} 22 re f\n`;
        stream += "0.031 0.290 0.184 rg\n";
        stream += `${margin} ${yPos - 5} 5 22 re f\n`; // Green bar accent

        stream += "BT\n";
        stream += "/F2 12 Tf 0.031 0.290 0.184 rg\n";
        stream += `${margin + 12} ${yPos} Td\n`;
        stream += `(${escapePdfText(item.text.toUpperCase())}) Tj\n`;
        stream += "ET\n";
        yPos -= 8;
      } else if (item.type === "subHeader") {
        yPos -= 20;
        stream += "BT\n";
        stream += "/F2 10.5 Tf 0.2 0.25 0.3 rg\n";
        stream += `${margin + 16} ${yPos} Td\n`;
        stream += `(>  ${escapePdfText(item.text)}) Tj\n`;
        stream += "ET\n";

        // Thin divider
        stream += "0.88 0.90 0.92 RG 0.5 w\n";
        stream += `${margin + 16} ${yPos - 4} m ${margin + contentWidth} ${yPos - 4} l S\n`;
        yPos -= 6;
      } else if (item.type === "item") {
        yPos -= 18;
        // Item bullet & text
        stream += "BT\n";
        stream += "/F1 10.5 Tf 0.12 0.12 0.12 rg\n";
        stream += `${margin + 26} ${yPos} Td\n`;
        const maxTextChars = doc.includePrices ? 45 : 55;
        const itemText =
          item.text.length > maxTextChars ? `${item.text.slice(0, maxTextChars - 1)}...` : item.text;
        stream += `(- ${escapePdfText(itemText)}) Tj\n`;
        stream += "ET\n";

        // Quantity in bold green
        stream += "BT\n";
        stream += "/F2 11 Tf 0.031 0.290 0.184 rg\n";
        const qtyText = `${item.quantity} pcs`;
        const qtyX = doc.includePrices ? margin + contentWidth - 110 : margin + contentWidth - 50;
        stream += `${qtyX} ${yPos} Td\n`;
        stream += `(${escapePdfText(qtyText)}) Tj\n`;
        stream += "ET\n";

        // Price if included
        if (doc.includePrices && item.price) {
          stream += "BT\n";
          stream += "/F1 10 Tf 0.3 0.3 0.3 rg\n";
          stream += `${margin + contentWidth - 55} ${yPos} Td\n`;
          stream += `(${escapePdfText(item.price)}) Tj\n`;
          stream += "ET\n";
        }
      }
    }

    // Page footer
    stream += "BT\n";
    stream += "/F1 9 Tf 0.5 0.5 0.5 rg\n";
    stream += `${margin} 25 Td\n`;
    stream += `(Generated via AHIA - Alaba & Trade Fair Market Operating System) Tj\n`;
    stream += `380 0 Td (Page ${pageNum} of ${totalPages}) Tj\n`;
    stream += "ET\n";

    // Stream object
    const streamBytes = new TextEncoder().encode(stream);
    const streamObjIndex = addObject(
      `<< /Length ${streamBytes.length} >>\nstream\n${stream}\nendstream`,
    );

    // Page Object
    const pageObjId = addObject(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Contents ${streamObjIndex} 0 R /Resources << /Font << /F1 ${fontRegularObj} 0 R /F2 ${fontBoldObj} 0 R >> >> >>`,
    );
    pageObjectIds.push(pageObjId);
  });

  // Finalize Object 2 (Pages list)
  const kidsStr = pageObjectIds.map((id) => `${id} 0 R`).join(" ");
  pdfObjects[pagesObjIndex - 1] = `<< /Type /Pages /Kids [${kidsStr}] /Count ${pageObjectIds.length} >>`;

  // Assemble complete PDF file
  let fullPdf = "%PDF-1.4\n";
  objectOffsets.push(0);

  for (let i = 0; i < pdfObjects.length; i++) {
    objectOffsets.push(fullPdf.length);
    fullPdf += `${i + 1} 0 obj\n${pdfObjects[i]}\nendobj\n`;
  }

  const xrefOffset = fullPdf.length;
  fullPdf += `xref\n0 ${pdfObjects.length + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= pdfObjects.length; i++) {
    const off = objectOffsets[i];
    fullPdf += `${off.toString().padStart(10, "0")} 00000 n \n`;
  }

  fullPdf += `trailer\n<< /Size ${pdfObjects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;

  return new Blob([new TextEncoder().encode(fullPdf)], { type: "application/pdf" });
}

export function downloadWaybillPdf(doc: WaybillDocument, filename: string): void {
  const blob = generateWaybillPdfBlob(doc);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".pdf") ? filename : `${filename}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
