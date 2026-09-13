# Decision Cards — audit sample (read-only, output.csv unchanged)

Cards: 250 (showing 10). Status {'affordable_now': 71, 'not_affordable': 70, 'affordable_with_plan': 66, 'affordable_later': 43}. Method {'full_payment': 72, 'not_recommended': 70, 'installments': 58, 'wait': 43, 'partial_payment': 7}.

Each card collates balance/cushion, recurring + pending + income, message/image evidence counts, eligibility gates for runner-up methods, and the shipped explanation. Full JSON: `code/state/decision_cards.json` (runtime cache, not shipped).

### request_26 (user_26) — affordable_now via full_payment
- Requested IDR 15,656,000, safe today IDR 15,656,000, earliest full: 2025-08-03
- Balance IDR 100,845,250 (min IDR 24,768,300, cushion IDR 76,076,950)
- Recurring ~IDR 13,230,348.84/mo x4, pending reserved IDR 0, confirmed income rows 0
- Plan: `2025-08-03:15656000` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 0 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments: 3 option(s), max 5 whole-months
> Pay IDR 15656000 today. This leaves at least IDR 24768300 available over the next 90 days.

### request_27 (user_27) — affordable_now via full_payment
- Requested ZAR 6,670, safe today ZAR 6,670, earliest full: 2026-07-05
- Balance ZAR 93,141.80 (min ZAR 20,500, cushion ZAR 72,641.80)
- Recurring ~ZAR 13,165.11/mo x6, pending reserved ZAR 0, confirmed income rows 0
- Plan: `2026-07-05:6670` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 0 OCR amounts
- Gates: installments not in user-accepted methods
> Pay ZAR 6670 today. This leaves at least ZAR 20500 available over the next 90 days.

### request_28 (user_28) — not_affordable via not_recommended
- Requested EUR 1,302.40, safe today EUR 310.70, earliest full: none-in-90d
- Balance EUR 1,789.40 (min EUR 1,100.00, cushion EUR 689.40)
- Recurring ~EUR 710.68/mo x6, pending reserved EUR 0.00, confirmed income rows 0
- Plan: `none` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 0 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments not in user-accepted methods
> Cannot safely afford EUR 1302.4 within 90 days. Paying more than EUR 310.7 today would take the balance below the EUR 1100 minimum.

### request_29 (user_29) — not_affordable via not_recommended
- Requested ZAR 51,524, safe today ZAR 32,532.19, earliest full: none-in-90d
- Balance ZAR 113,540.10 (min ZAR 28,300, cushion ZAR 85,240.10)
- Recurring ~ZAR 18,837.97/mo x7, pending reserved ZAR 0, confirmed income rows 0
- Plan: `none` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 0 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments: 1 option(s), max 5 whole-months
> Cannot safely afford ZAR 51524 within 90 days. Paying more than ZAR 32532.19 today would take the balance below the ZAR 28300 minimum.

### request_30 (user_30) — affordable_with_plan via installments
- Requested USD 775.20, safe today USD 775.20, earliest full: 2026-04-06
- Balance USD 3,752.72 (min USD 900.00, cushion USD 2,852.72)
- Recurring ~USD 584.35/mo x5, pending reserved USD 0.00, confirmed income rows 0
- Plan: `2026-04-06:268.74|2026-05-06:268.74|2026-06-05:268.74` | Spending: `none`
- Evidence: 0 amendments, 0 quarantined, 0 OCR amounts
- Gates: full_payment not in user-accepted methods; partial_payment blocked: request allows_partial=false; installments: 2 option(s), max 4 whole-months
> Use 3 installments of USD 268.74, starting 2026-04-06. This leaves at least USD 900 available.

### request_31 (user_31) — affordable_later via wait
- Requested IDR 18,164,000, safe today IDR 5,582,071.93, earliest full: 2024-10-15
- Balance IDR 30,429,260 (min IDR 16,588,900, cushion IDR 13,840,360)
- Recurring ~IDR 8,643,337.23/mo x6, pending reserved IDR 0, confirmed income rows 1
- Plan: `2024-10-15:18164000` | Spending: `none`
- Evidence: 0 amendments, 0 quarantined, 0 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments: 1 option(s), max 6 whole-months
> Pay IDR 18164000 in full on 2024-10-15. Paying earlier would take the balance below the IDR 16588900 minimum.

### request_32 (user_32) — not_affordable via not_recommended
- Requested ZAR 40,018, safe today ZAR 0, earliest full: none-in-90d
- Balance ZAR 69,005.80 (min ZAR 35,700, cushion ZAR 33,305.80)
- Recurring ~ZAR 29,558.42/mo x6, pending reserved ZAR 0, confirmed income rows 0
- Plan: `none` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 0 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments not in user-accepted methods
> Cannot safely afford ZAR 40018 within 90 days. Paying more than ZAR 0 today would take the balance below the ZAR 35700 minimum.

### request_33 (user_33) — affordable_later via wait
- Requested INR 118,000, safe today INR 51,705.73, earliest full: 2026-01-15
- Balance INR 167,280 (min INR 102,100, cushion INR 65,180)
- Recurring ~INR 69,058.06/mo x7, pending reserved INR 0, confirmed income rows 0
- Plan: `2026-01-15:118000` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 1 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments not in user-accepted methods
> Pay INR 118000 in full on 2026-01-15. Paying earlier would take the balance below the INR 102100 minimum.

### request_34 (user_34) — affordable_now via full_payment
- Requested INR 129,400, safe today INR 129,400, earliest full: 2024-12-04
- Balance INR 559,752.50 (min INR 138,500, cushion INR 421,252.50)
- Recurring ~INR 77,333.93/mo x5, pending reserved INR 0, confirmed income rows 0
- Plan: `2024-12-04:129400` | Spending: `none`
- Evidence: 1 amendments, 0 quarantined, 0 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments not in user-accepted methods
> Pay INR 129400 today. This leaves at least INR 138500 available over the next 90 days.

### request_35 (user_35) — affordable_later via wait
- Requested INR 212,000, safe today INR 56,140.39, earliest full: 2025-12-15
- Balance INR 231,530 (min INR 106,400, cushion INR 125,130)
- Recurring ~INR 70,264.61/mo x6, pending reserved INR 0, confirmed income rows 0
- Plan: `2025-12-15:212000` | Spending: `none`
- Evidence: 2 amendments, 0 quarantined, 1 OCR amounts
- Gates: partial_payment blocked: request allows_partial=false; installments not in user-accepted methods
> Pay INR 212000 in full on 2025-12-15. Paying earlier would take the balance below the INR 106400 minimum.
