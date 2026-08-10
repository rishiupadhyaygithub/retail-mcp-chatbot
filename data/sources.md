# Corpus sources — Retail / e-commerce (Phase 1)

Public documentation only. Four companies chosen for genuinely conflicting return/warranty policies + differing vocabulary. Target 15–40 documents, mixed length, ≥1 deliberate contradiction pair.

> **How to use this file:** the URLs below are the canonical help-center entry points per company × topic. At ingestion, open each, capture the exact policy page, save it as markdown under `data/corpus/<company>/<topic>.md` with `##` section headings, and paste the **exact final URL** into the "Pinned URL" column. Mark `[verify]` rows once confirmed live.

## document_type taxonomy
`returns` · `warranty` · `delivery` · `payments` · `order_tracking`

---

## Amazon
| document_type | Entry point | Pinned URL (fill at ingestion) |
|---|---|---|
| returns | amazon.com → Help → Returns & Refunds → "Return Items You Ordered" / "Refunds" | `[verify]` |
| delivery | amazon.com → Help → Shipping & Delivery → "Late Deliveries" / "Missing Package" | `[verify]` |
| payments | amazon.com → Help → Payments & Gift Cards → "Charged Twice" / payment methods | `[verify]` |
| warranty | amazon.com → Help → warranty / "Product Warranty Claims" | `[verify]` |
| order_tracking | amazon.com → Help → "Track Your Package" / order status | `[verify]` |

## Best Buy
| document_type | Entry point | Pinned URL (fill at ingestion) |
|---|---|---|
| returns | bestbuy.com → Help Topics → **Return & Exchange Policy** (15-day standard; restocking fee on some electronics) | `[verify]` |
| warranty | bestbuy.com → Help → Geek Squad / manufacturer warranty | `[verify]` |
| delivery | bestbuy.com → Help → Shipping, Delivery & Pickup | `[verify]` |
| payments | bestbuy.com → Help → Payment options / billing | `[verify]` |
| order_tracking | bestbuy.com → Help → Track Order / order status | `[verify]` |

## IKEA (US)
| document_type | Entry point | Pinned URL (fill at ingestion) |
|---|---|---|
| returns | ikea.com/us → Customer Service → **Returns & Claims** (365-day return terms — differs sharply from the others) | `[verify]` |
| warranty | ikea.com/us → Customer Service → warranties / guarantees | `[verify]` |
| delivery | ikea.com/us → Customer Service → Delivery | `[verify]` |
| payments | ikea.com/us → Customer Service → payment & financing | `[verify]` |
| order_tracking | ikea.com/us → Customer Service → Track your order | `[verify]` |

## Target
| document_type | Entry point | Pinned URL (fill at ingestion) |
|---|---|---|
| returns | help.target.com → **Returns** (90-day standard; different windows for electronics / registry) | `[verify]` |
| warranty | help.target.com → warranties / Target Plus | `[verify]` |
| delivery | help.target.com → Shipping & Delivery | `[verify]` |
| payments | help.target.com → Payments / RedCard | `[verify]` |
| order_tracking | help.target.com → Track order / order status | `[verify]` |

---

## Deliberate contradiction pair (the eval hinges on this)
- **Amazon ~30-day standard return window** vs **Best Buy 15-day window (+ restocking fee on some electronics)**.
- Bonus spread: **IKEA 365-day** and **Target 90-day** — four different return windows for "how long do I have to return this?" The system must return the *right company's* number, not blend them.

## Vocabulary conflicts to preserve (do not normalize)
- "return" (Amazon/Target) vs "return & exchange" (Best Buy) vs "returns & claims" (IKEA)
- "refund" vs "money back" vs "credit"
- "package/shipment" vs "parcel" vs "order"
- "restocking fee" (Best Buy) vs no such concept (IKEA)

## Length mix (uniform length hides chunking bugs)
- **Short:** a single order-tracking or account FAQ (~50–100 words).
- **Long:** a full terms-of-sale / limited-warranty disclosure (several thousand words, many `##` subsections).
- Aim ≥3 short + ≥3 long across the four companies.

## Rules
- Public pages only. No login-walled or account-specific content.
- Save each as markdown with `##` headings marking real topic boundaries (chunker splits on these).
- Record the retrieval date next to each pinned URL (policies change).
