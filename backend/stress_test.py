import fitz, time, tracemalloc, sys

pdf_path = sys.argv[1]
doc = fitz.open(pdf_path)
total_pages = len(doc)
full_text = ""
tracemalloc.start()
t0 = time.time()

for i, page in enumerate(doc, start=1):
    full_text += page.get_text()
    if i % 50 == 0:
        current, peak = tracemalloc.get_traced_memory()
        print(f"page {i}/{total_pages} | peak {peak/1024/1024:.1f} MB | {time.time()-t0:.1f}s")

current, peak = tracemalloc.get_traced_memory()
print(f"FINAL pages={total_pages} chars={len(full_text)} peak={peak/1024/1024:.1f}MB time={time.time()-t0:.1f}s")
doc.close()