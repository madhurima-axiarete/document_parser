# Test 01 - Image Across Page Boundary

Purpose: same tall figure intentionally cut across two PDF pages.

> **[Figure]** Top half of a service architecture diagram showing a flow of services connected by arrows. Row 1: Service 1 (ID SVC-100, blue) → Service 2 (ID SVC-101, green) → Service 3 (ID SVC-102, peach/orange). Row 2: Service 4 (ID SVC-103, purple) → Service 5 (ID SVC-104, blue) → Service 6 (ID SVC-105, green). Row 3: Service 7 (ID SVC-106, peach/orange) → Service 8 (ID SVC-107, purple) → Service 9 (ID SVC-108, blue). Diagonal connector lines link the rows. A red horizontal line near the bottom of the figure marks the page boundary, with a red label reading 'IMPORTANT: THIS FIGURE CONTINUES ON NEXT PAGE - boundary line must reconcile'. Partially visible Row 4 at bottom: Service 10 (ID SVC-109, green) → Service 11 (ID SVC-110, peach/orange) → Service 12 (ID SVC-111, purple).

Figure 1a. Top half of architecture diagram. Continuation marker at bottom.

# Test 01 - Image Across Page Boundary, continued

> **[Figure]** Bottom half of a service architecture diagram, continuing from previous page. A red horizontal line at the top of the figure marks the page boundary continuation, with a label reading 'IMPORTANT: THIS FIGURE CONTINUES ON NEXT PAGE - boundary line must reconcile'. Row 4 (repeated/continued): Service 10 (ID SVC-109, green) → Service 11 (ID SVC-110, peach/orange) → Service 12 (ID SVC-111, purple). Diagonal connector lines link to subsequent rows. Row 5: Service 13 (ID SVC-112, blue) → Service 14 (ID SVC-113, green) → Service 15 (ID SVC-114, peach/orange). Row 6: Service 16 (ID SVC-115, purple) → Service 17 (ID SVC-116, blue) → Service 18 (ID SVC-117, green). Diagonal connector lines link the rows.

Figure 1b. Bottom half of same architecture diagram. Parser should merge with previous page.