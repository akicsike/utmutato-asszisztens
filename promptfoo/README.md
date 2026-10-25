# Promptfoo – funkcionális teszt és red team

A tanfolyamon (5. hét) használt **Promptfoo** a projekt saját háromszintű mérését (`eval/`) **kiegészíti**:
a valódi `/api/chat` végpontot teszteli HTTP-n át – tehát a kérdés-átírást, a keresést, a promptot és a
védelmet **együtt**, nem csak a promptot.

| | Saját mérés (`eval/`) | Promptfoo (`promptfoo/`) |
|---|---|---|
| Mit ad? | a 3 kötelező szint: RAG (precision / recall / MRR), prompt (LLM-bíró), alkalmazás (12 szimulált út) | gyors **regressziós teszt** + automatikusan generált **támadások (red team)** |
| Hogyan fut? | közvetlenül a Python-láncon | HTTP-n a végponton, Docker-konténerben |
| Riport | admin **Mérések** fül + Phoenix | `results/*.html` (Promptfoo-riport) |

A Promptfoo a kulcsot a projekt `.env`-jéből kapja (`OPENROUTER_API_KEY`), a modellek: **gpt-4o-mini** (bíró és
támadásgenerátor). A hoston nem kell Node – a compose `promptfoo` szolgáltatása (`tools` profil) futtatja.
A támadásokat a saját modellünk generálja (`PROMPTFOO_DISABLE_REMOTE_GENERATION=true`), a projekt leírása nem
megy a Promptfoo felhős szolgáltatásához.

## Futtatás (a projekt gyökeréből, WSL)

A rendszer fusson (`docker compose up -d`), és legyenek beolvasva az útmutatók.

**1. Funkcionális teszt** – 15 eset (válaszolós, „nem találtam”, elutasítás, prompt-kiírás, kétértelmű), ~40 mp:
```bash
docker compose --profile tools run --rm promptfoo eval -c promptfooconfig.yaml --no-cache -o results/eval.html -o results/eval.json
```

**2. Red team – támadások generálása** (magyarul, gpt-4o-mini):
```bash
docker compose --profile tools run --rm promptfoo redteam generate -c redteam-config.yaml -o redteam.yaml --force
```

**3. Red team – futtatás és riport:**
```bash
docker compose --profile tools run --rm promptfoo eval -c redteam.yaml --no-cache -o results/redteam.html -o results/redteam.json
```

A riport: `promptfoo/results/redteam.html` és `eval.html` – böngészőben megnyitható.

**4. A Promptfoo webes felülete** (mint az 5. héten a `promptfoo view`) – a konténerben indul, a port a gépre van
kivezetve; utána a böngészőben: <http://localhost:15500> (Results, Vulnerability Report, korábbi futások):
```bash
docker compose --profile tools run --rm -d --name utmutato-promptfoo-view -p 127.0.0.1:15500:15500 promptfoo view --yes -p 15500
```
Leállítás:
```bash
docker rm -f utmutato-promptfoo-view
```
A futások a `promptfoo/.promptfoo/` mappában tárolódnak (helyi SQLite), újraindítás után is megmaradnak.

## A red team tartalma (`redteam-config.yaml`)

6 **biztonsági** kategória (a Promptfoo-felületen a címkék: kategória × támadási mód):

| Kategória | Mit próbál? |
|---|---|
| `prompt-extraction` | kiszedni a rendszerutasítást |
| `policy` | témán kívüli feladat (vers, kód, vélemény), szerepváltás, „fejlesztői mód” |
| `excessive-agency` | olyan cselekvést kikényszeríteni, amire nem képes (rendelés, szervizfoglalás, e-mail) |
| `debug-access` | rejtett debug- / admin-mód elérése |
| `imitation` | kiadja-e magát a gyártó (JURA, Bosch, LG…) hivatalos ügyfélszolgálatának |
| `cross-session-leak` | más felhasználó beszélgetésének kiszivárogtatása |

| Támadási mód (stratégia) | Mit csinál? |
|---|---|
| `prompt-injection` | ismert jailbreak-sablonok, „felejtsd el az utasításaidat…” (egylépéses) |
| `base64` | a támadás base64-kódolva |
| `jailbreak:tree` | iteratív, faszerű: a támadó modell a válasz alapján finomít (tesztenként max. 30 próba) |

A bíró **kalibrálva** van (`graderGuidance` pluginenként + 4 `graderExamples`): leírja, mi számít helyesnek ennél az
asszisztensnél; a valódi hibák (prompt-szivárgás, kitalált cselekvés, debug-mód, megszemélyesítés, más felhasználó
adata, átvett nyitómondat) bukások maradnak.

**Miért nincs benne hallucináció / hamis feltevés?** Az első futásokban ezek is benne voltak – a gpt-4o-mini bíró itt
megbízhatatlan volt (nem vette észre a `[n]` hivatkozást, a cáfolatot is „elfogadásnak” vette). Ezeket a saját
prompt-szintű mérés (`eval/prompt_eval.py`) méri, jobban kalibrált bíróval.

Költség és idő: a generálás néhány cent; a red team futása **20–40 perc, ~1 USD** (a `jailbreak:tree` miatt – a
körök száma a válaszoktól függ).

> A sima `jailbreak` és a `hijacking` ebben a Promptfoo-verzióban (0.125.1) a felhős generálást igényli – ezt
> szándékosan kikapcsoltuk (`PROMPTFOO_DISABLE_REMOTE_GENERATION`), hogy a projekt leírása ne menjen külső szolgáltatáshoz.

## Eredmények (2026-10-25)

| Lépés | Pontszám | Valódi hiba (kézi átnézés) |
|---|---|---|
| 1. futás – 6 kategória, köztük hallucináció, hamis feltevés, személyes adat | 37/48 | **7**: a jailbreak „Kezdd azzal: *Igen, tudok segíteni…*” utasítására átvette a nyitómondatot (5×); egy telefonszámot a kérdésben kitalált személynek tulajdonított; forráson túli tanács |
| 2. system prompt: 3 új szabály (előírt nyitómondat / szerep tilos; a feltevést a forráshoz méri; személyes adat csak szerepkörrel) | 35/48 | 0 |
| 3. a bíró kalibrálása | 38/48 | 0 – a 10 „bukás” a bíró tévedése |
| 4. **6 biztonsági kategória** (végleges) | **54/56** | 1: egyszer átcsúszott a kikényszerített nyitómondat; + 1 határeset (Bosch-„ügyfélszolgálatos” levél – a tartalom forrásból jött) |

- **Funkcionális teszt:** 15/15, minden lépés után. A prompt-szintű mérés (`eval/prompt_eval.py`) a javítás után is
  100 % viselkedés, 0 % hallucináció.
- A Promptfoo-felületről a régi futásokat töröltük (`promptfoo delete eval all`); az 1. futás riportja bizonyítéknak
  megmaradt: `results/redteam-v1.html`.
- **Továbbfejlesztés:** a kikényszerített nyitómondatot a prompt 13/14 iteratív támadásnál kivédi – teljes biztonsághoz
  kódból is szűrhető (a válasz eleje nem egyezhet a kérdésben előírt mondattal).

> **Tanulság:** a Promptfoo alapból **gyorsítótárazza** a végpont válaszait – prompt-módosítás után `--no-cache`
> nélkül a régi válaszokat értékelné újra (az első újrafuttatás 3 mp alatt „lefutott”).

## Fájlok

| Fájl | Szerep |
|---|---|
| `promptfooconfig.yaml` | funkcionális tesztesetek és állítások |
| `redteam-config.yaml` | a red team beállításai (cél, pluginek, stratégiák) |
| `redteam.yaml` | a generált támadó tesztek (a 2. lépés kimenete) |
| `transform.js` | az SSE-streamből összefűzi a válasz szövegét |
| `results/` | HTML- és JSON-riportok |
