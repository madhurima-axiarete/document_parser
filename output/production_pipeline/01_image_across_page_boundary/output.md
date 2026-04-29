# Test 01 - Image Across Page Boundary

Purpose: same tall figure intentionally cut across two PDF pages.

> **[Figure]** Top half of an architecture diagram showing a service flow. The diagram contains four rows of connected service nodes, each row with three boxes linked by arrows from left to right. Row 1: Service 1 (ID SVC-100, blue) -> Service 2 (ID SVC-101, green) -> Service 3 (ID SVC-102, orange). Row 2: Service 4 (ID SVC-103, purple) -> Service 5 (ID SVC-104, blue) -> Service 6 (ID SVC-105, green). Row 3: Service 7 (ID SVC-106, orange) -> Service 8 (ID SVC-107, purple) -> Service 9 (ID SVC-108, blue). Row 4 (partially visible, cut by page boundary red line): Service 10 (ID SVC-109, green) -> Service 11 (ID SVC-110, orange) -> Service 12 (ID SVC-111, purple). Diagonal connector lines link rows sequentially. A red horizontal line marks the page boundary near the bottom. Red text reads: 'IMPORTANT: THIS FIGURE CONTINUES ON NEXT PAGE - boundary line must reconcile'.

Figure 1a. Top half of architecture diagram. Continuation marker at bottom.

# Test 01 - Image Across Page Boundary, continued

> **[Figure]** Bottom half of the same architecture diagram continuing from page 1. A red horizontal line at the top marks the page boundary continuation point with red text reading: 'IMPORTANT: THIS FIGURE CONTINUES ON NEXT PAGE - boundary line must reconcile'. The diagram shows three rows of connected service nodes: Row 4 (continued from page 1): Service 10 (ID SVC-109, green) -> Service 11 (ID SVC-110, orange) -> Service 12 (ID SVC-111, purple). Row 5: Service 13 (ID SVC-112, blue) -> Service 14 (ID SVC-113, green) -> Service 15 (ID SVC-114, orange). Row 6: Service 16 (ID SVC-115, purple) -> Service 17 (ID SVC-116, blue) -> Service 18 (ID SVC-117, green). Diagonal connector lines link rows sequentially.

Figure 1b. Bottom half of same architecture diagram. Parser should merge with previous page.