# Mérési eredmények (Evaluation)

> **A teljes, interaktív riport:** [`docs/evaluation.html`](docs/evaluation.html) – összefoglaló, módszertan, diagramok,
> kérdésenkénti / esetenkénti / utankénti részletek (lenyitható), hibaelemzés, korlátok. A GitHub a HTML-t nem
> jeleníti meg: nyisd meg [előnézetben](https://htmlpreview.github.io/?https://github.com/akicsike/utmutato-asszisztens/blob/main/docs/evaluation.html) vagy klónozás után helyben, böngészővel.
>
> Ez a fájl és a HTML is **generált**: `python eval/report.py` (az `eval/results/*.json` és a `promptfoo/results/*.json` alapján).

## Összefoglaló

| Szint | Adatkészlet | Fő eredmény |
|---|---|---|
| 1. RAG | 30 kérdés, elvárt útmutató + oldal | hit@6 **1,00** · recall@6 **0,96** · MRR **0,92** · precision@6 0,44 |
| 2. Prompt | 17 eset, LLM-bíró (gpt-4o-mini) | viselkedés **100 %** · helyesség **1,00** · hallucináció **0 %** · kontextus-relevancia 0,81 |
| 3. Alkalmazás | 12 többfordulós út, szimulált felhasználó | célelérés **100 %** · elégedettség **4,7/5** · forráshű fordulók 85 % · első token p50 3,4 s · $0,006/út |
| Kiegészítés | Promptfoo a valódi `/api/chat` ellen | funkcionális **15/15** · red team **54/56** elhárítva (6 biztonsági kategória × 3 támadási mód) |

## 1. RAG-szint (k = 6)

| Változat | precision@6 | recall@6 | hit@6 | MRR |
|---|---|---|---|---|
| dense | 0,45 | 0,92 | 0,97 | 0,93 |
| bm25 | 0,37 | 0,86 | 0,97 | 0,76 |
| hibrid (RRF) | 0,46 | 0,95 | 1,00 | 0,84 |
| hibrid + rerank | 0,44 | 0,96 | 1,00 | 0,92 |
| fixed · hibrid + rerank | 0,43 | 0,97 | 1,00 | 0,94 |
| text-embedding-3-small · hibrid + rerank | 0,44 | 0,97 | 1,00 | 0,92 |
| qwen3-embedding-8b · hibrid + rerank | 0,46 | 0,96 | 1,00 | 0,92 |

A rerank (Cohere rerank-v3.5, cross-encoder) a hibrid keresés sorrendjét javítja (MRR 0,84 → 0,92);
rerank után a három embedding-modell és a két chunkolás gyakorlatilag egyforma – maradt a kisebb bge-m3 és a szerkezet szerinti chunk.

## 2. Prompt-szint

| Mérőszám | 1. futás | utolsó futás |
|---|---|---|
| elvárt viselkedés | 94 % | **100 %** |
| helyesség (válaszolós) | 0,90 | **1,00** |
| hallucinációs arány | 14 % | **0 %** |
| kontextus-relevancia | 0,79 | 0,81 |
| első token / teljes idő p50 | 3,5 s / 3,9 s | 3,1 s / 4,1 s |

Az 1. futás után: a DJI-kérdés keresési hibája (tokenizáló + kulcsszavak) és a bíró egy téves hallucináció-jelölése (bíró-prompt) javítva.

## 3. Alkalmazás-szint

Célelérés 100 %, elégedettség 4,7/5, válaszminőség 4,7/5,
első token p50 / p95 3,4 / 7,3 s, teljes idő 4,7 / 10,4 s.
A gyenge pont: utókérdéseknél, amire az útmutató már nem felel, előfordul alátámasztatlan kiegészítés (forráshű fordulók 85 %).

## Korlátok – röviden

- **Egy futás, nincs szórás.** Minden szintet egyszer futtattunk (a prompt-szintet háromszor, változtatások között). Az LLM-bíró és a modell is véletlenszerű – az egy-egy esetnyi eltérések (pl. p02 helyessége 0,83 → 0,94) zajnak tekintendők.
- **A bíró ugyanaz a modell, mint a válaszoló (gpt-4o-mini).** Ez önértékelési torzítást okozhat; a Promptfoo red teamben a bíró megbízhatatlansága ki is jött (helyes, hivatkozott válaszokat is bukásnak jelölt). Erősebb bíróval (pl. GPT-4.1 / Claude) érdemes megismételni.
- **Kicsi, saját összeállítású kérdéssor.** 30 RAG-kérdés, 17 prompt-eset, 12 út – mindet én írtam és ellenőriztem az útmutatók alapján; a valódi felhasználók kérdései (Analitika fül, visszajelzések) ettől eltérhetnek.
- **A precision@6 felső korlátja alacsony.** Egy kérdésre jellemzően 1–3 releváns chunk van, a 6 találatból a többi szükségszerűen nem releváns – ezért a ~0,45 nem rossz érték; a recall, a hit és az MRR a beszédesebb.
- **Oldalszintű relevancia.** Egy találat akkor releváns, ha az elvárt útmutatóból jön és oldaltartománya metszi az elvárt oldalakat – egy hosszú oldalon a nem a választ tartalmazó chunk is relevánsnak számít.
- **A szimulált felhasználó is LLM.** Az elégedettség (1–5) a persona szemével adott bírói pontszám, nem valódi felhasználói értékelés; a valódit a 👍/👎 visszajelzés gyűjti.
- **A latencia hálózatfüggő.** Az OpenRouter-hívások ideje változik; a prompt-szinten a p09 első tokenje 48 s volt (egyszeri szolgáltatói kiugrás) – ezért p50 / p95 szerepel, nem átlag.

## Reprodukálás

```bash
docker compose exec api python /eval/run_all.py   # a 3 szint (~15 perc, ~1 USD)
python eval/report.py                             # docs/evaluation.html + EVALUATION.md újragenerálása
```
Promptfoo: lásd [`promptfoo/README.md`](promptfoo/README.md).
