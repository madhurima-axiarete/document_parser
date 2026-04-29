import { readFileSync } from "fs";

// Compare old vs new output
const oldText = readFileSync("output/liteparse/PerformanceCharts.txt", "utf8");
const newJson = JSON.parse(
  readFileSync("output/liteparse_improved/PerformanceCharts.json", "utf8")
);

console.log("=== COMPARISON: Old vs Improved LiteParse ===\n");

console.log("📊 OLD OUTPUT (plain text):");
console.log(`  Size: ${oldText.length} chars`);
console.log(`  Type: Raw text only`);
console.log(`  Layout info: ❌ None`);
console.log(`  Bounding boxes: ❌ None`);
console.log(`  Confidence scores: ❌ None\n`);

console.log("✨ NEW OUTPUT (JSON with structure):");
const firstPage = newJson.data.pages[0];
console.log(`  Size: ${JSON.stringify(newJson).length} chars`);
console.log(`  Type: Structured JSON`);
console.log(`  Pages: ${newJson.data.pages.length}`);
console.log(`  First page dimensions: ${firstPage.width} × ${firstPage.height}`);
console.log(`  Text items with bounding boxes: ${firstPage.textItems.length}`);
console.log(`  Layout info: ✅ Yes (x, y, width, height)`);
console.log(`  Bounding boxes: ✅ Yes (precise coordinates)`);
console.log(`  Confidence scores: ✅ Yes (per word)\n`);

console.log("📌 SAMPLE TEXT ITEM WITH METADATA:");
const sampleItem = firstPage.textItems[0];
console.log(JSON.stringify(sampleItem, null, 2));

console.log("\n🔍 WHAT THIS ENABLES:");
console.log("  ✅ Group words by proximity (detect sentences, tables)");
console.log("  ✅ Detect charts by analyzing empty space and number positions");
console.log("  ✅ Preserve page layout for post-processing");
console.log("  ✅ Filter low-confidence OCR results");
console.log("  ✅ Extract tables by analyzing coordinate patterns");
console.log("  ✅ Reconstruct document structure programmatically");

console.log("\n💡 NEXT STEP: Use this structure with Claude:");
console.log("  1. Parse textItems by location (x,y coordinates)");
console.log("  2. Group items that are close together");
console.log("  3. Detect tables/lists by alignment patterns");
console.log("  4. Feed both text AND layout info to Claude");
console.log("  5. Claude understands 'Chart at 300,400' is better than scattered numbers");
