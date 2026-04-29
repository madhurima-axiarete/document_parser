import { LiteParse } from "@llamaindex/liteparse";
import { writeFile } from "fs/promises";
import { basename } from "path";

const filePath = "/Users/madhurimachakraborty/document_parser/test_docs/salesforce_release_notes_3-25-2026.pdf";

async function main() {
  console.log(`Testing LiteParse on large file: ${basename(filePath)}`);
  console.log(`File size: 43 MB`);
  
  const parser = new LiteParse({ ocrEnabled: true });
  
  try {
    const start = Date.now();
    console.log("\nParsing started...");
    
    const result = await parser.parse(filePath);
    
    const elapsed = ((Date.now() - start) / 1000).toFixed(2);
    console.log(`\n✓ Parsing completed in ${elapsed}s`);
    
    const text = result.text ?? "";
    console.log(`\nExtracted text length: ${text.length} characters`);
    console.log(`Approximate word count: ${text.split(/\s+/).length}`);
    
    // Sample first 1000 chars
    console.log("\n--- Sample of extracted text (first 500 chars) ---");
    console.log(text.slice(0, 500));
    console.log("\n...\n");
    
    // Save output
    const outPath = "/Users/madhurimachakraborty/document_parser/output/liteparse/salesforce_release_notes.txt";
    await writeFile(outPath, text, "utf8");
    console.log(`✓ Saved to: ${outPath}`);
    
  } catch (err) {
    console.error(`✗ ERROR: ${err.message}`);
    if (err.stack) {
      console.error(err.stack);
    }
  }
}

main();
