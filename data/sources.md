# Corpus sources — Retail / e-commerce (Phase 1)

Public documentation only. Four companies chosen for genuinely conflicting return/warranty policies + differing vocabulary. Target 15–40 documents, mixed length, ≥1 deliberate contradiction pair.

> **Status (2026-08-11): 16 documents sourced**, 4 per company. Each is saved under `data/corpus/<company>/<topic>.md` with `##` section headings and YAML frontmatter (`source_url`, `retrieved`). Amazon and Best Buy help pages hard-block automated fetch (503 / timeout); their content was captured via search of the live public pages. IKEA and Target fetched directly.

## document_type taxonomy
`returns` · `warranty` · `delivery` · `payments` · `order_tracking`

---

## Amazon
| document_type | file | Pinned URL | retrieved |
|---|---|---|---|
| returns | `amazon/returns.md` | https://www.amazon.com/gp/help/customer/display.html?nodeId=GKM69DUUYKQWKWX7 | 2026-08-11 |
| payments (refund timelines) | `amazon/refund_timelines.md` | https://www.amazon.com/gp/help/customer/display.html?nodeId=GKQNFKFK5CF3C54B | 2026-08-11 |
| delivery | `amazon/delivery.md` | https://www.amazon.com/gp/help/customer/display.html?nodeId=GE66DNRRQVDZAR5E | 2026-08-11 |
| order_tracking | `amazon/order_tracking.md` | https://www.amazon.com/gp/help/customer/display.html?nodeId=GENAFPTNLHV7ZACW | 2026-08-11 |

## Best Buy
| document_type | file | Pinned URL | retrieved |
|---|---|---|---|
| returns | `bestbuy/returns.md` | https://www.bestbuy.com/site/help-topics/return-exchange-policy/pcmcat260800050014.c?id=pcmcat260800050014 | 2026-08-11 |
| warranty (Geek Squad) | `bestbuy/warranty.md` | https://www.bestbuy.com/site/geek-squad/geek-squad-protection/pcmcat159800050001.c?id=pcmcat159800050001 | 2026-08-11 |
| delivery | `bestbuy/delivery.md` | https://www.bestbuy.com/site/help-topics/shipping-delivery-store-pickup/pcmcat316000050003.c?id=pcmcat316000050003 | 2026-08-11 |
| payments | `bestbuy/payments.md` | https://www.bestbuy.com/site/help-topics/payment-options/pcmcat203400050003.c?id=pcmcat203400050003 | 2026-08-11 |

## IKEA (US)
| document_type | file | Pinned URL | retrieved |
|---|---|---|---|
| returns | `ikea/returns.md` | https://www.ikea.com/us/en/customer-service/returns-claims/ | 2026-08-11 |
| warranty | `ikea/warranty.md` | https://www.ikea.com/us/en/customer-service/knowledge/guarantees/ | 2026-08-11 |
| delivery | `ikea/delivery.md` | https://www.ikea.com/us/en/customer-service/services/delivery/ | 2026-08-11 |
| order_tracking | `ikea/order_tracking.md` | https://www.ikea.com/us/en/customer-service/track-manage-order/ | 2026-08-11 |

## Target
| document_type | file | Pinned URL | retrieved |
|---|---|---|---|
| returns | `target/returns.md` | https://www.target.com/help/articles/returns-exchanges/returns | 2026-08-11 |
| warranty (Allstate) | `target/warranty.md` | https://www.target.com/help/articles/product-support-services/target-protection-plans | 2026-08-11 |
| delivery | `target/delivery.md` | https://www.target.com/help/articles/delivery-options/ship-to-home | 2026-08-11 |
| payments (Circle Card) | `target/payments.md` | https://www.target.com/help/articles/target-circle/about-target-circle-card | 2026-08-11 |

---

## Deliberate contradiction pair (the eval hinges on this)
- **Amazon 30-day standard return window** vs **Best Buy 15-day window** (14-day for cellular; 60-day for Plus/Total members).
- Bonus spread: **IKEA 365-day** (180 open / 90 mattress) and **Target 90-day** (30 electronics / 14 Apple) — four different return windows for "how long do I have to return this?" The system must return the *right company's* number, not blend them.

## Vocabulary conflicts preserved (not normalized)
- "return" (Amazon/Target) vs "return & exchange" (Best Buy) vs "returns & claims" (IKEA)
- "refund" vs "money back" vs "credit"
- "package/shipment" vs "parcel" vs "order"
- "restocking fee" (Best Buy) vs "No Lemon Policy" (Target) vs no such concept (IKEA)

## Length mix
- **Short:** IKEA warranty, Amazon refund timelines (~3 sections).
- **Long:** IKEA delivery (6 delivery tiers), Best Buy returns (windows + memberships + categories), Target returns (standard + electronics + registry + refund timing).

## Rules honored
- Public pages only. No login-walled or account-specific content.
- Each saved as markdown with `##` headings marking real topic boundaries (chunker splits on these).
- Retrieval date recorded in each file's frontmatter (policies change).
