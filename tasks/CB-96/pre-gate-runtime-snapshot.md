# CB-96 — snapshot параллельного runtime executor

Jira comment 10351 зафиксировал отдельный runtime executor с ownership только
над static UI и browser test. Planning agent эти файлы не изменяет и до двух
approved plan reviews не использует их как implementation evidence.

Snapshot на 2026-08-19 18:13 local:

| Файл | Diff +/− | SHA-256 working copy |
|---|---:|---|
| `src/community_bot/transport/static/app.js` | +261/−10 | `43DF4629D3CB8A4418850A639F783E1DCEF94532472539E94791E09635EB2DD8` |
| `src/community_bot/transport/static/index.html` | +16/−15 | `F347A46BD267F64E97AB48190357BD97C82502AA2C6793ECBF7A291533B5B304` |
| `src/community_bot/transport/static/styles.css` | +71/−19 | `C4F915149BB701F1A911742D144890FB0BDD6C28C54E5CBD2B47EB464C7E0297` |
| `tests/browser/test_mini_app.py` | +109/−0 | `7E938C840BEEA9E6B774FC275DD1ACA58869BBDE2BD2892B7034A3D4B55F1354` |

Это наблюдение, не approval и не ownership transfer. Перед implementation/
review снимается новый snapshot; изменения проверяются против утверждённого
manifest и могут быть переработаны без отката несвязанных правок.
