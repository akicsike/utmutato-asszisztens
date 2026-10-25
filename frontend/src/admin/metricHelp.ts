// Közérthető magyarázat az admin felület mutatóihoz (a csempék és a táblázat-fejlécek title-tooltipje).
// A kulcs a megjelenített felirat kisbetűsen; a "@6"-féle k-értéket a kereső "@k"-ra cseréli.

const P50_P95 = "P50 (medián): a válaszok fele ennél gyorsabb. P95: a válaszok 95 %-a ennél gyorsabb – a lassú esetek mutatója.";

const HELP: Record<string, string> = {
  // ---- Mérések · RAG-szint
  "kérdés": "Hány tesztkérdésen futott a mérés. Mindegyikhez előre tudjuk, melyik útmutató melyik oldalán van a helyes válasz.",
  "precision@k": "Pontosság: a keresés által visszaadott találatok hány százaléka releváns (a jó útmutató jó oldaláról való). 1 = mind releváns. Kb. 0,45 itt természetes, mert egy kérdésre általában csak 1–3 jó részlet létezik.",
  "recall@k": "Fedés: a helyes választ tartalmazó oldalak hány százalékát hozta fel a keresés. 1 = minden szükséges oldalt megtalált.",
  "hit@k": "Találati arány: a kérdések hány százalékánál van legalább egy jó találat a visszaadottak között. 1 = minden kérdésnél megtalálta a választ tartalmazó oldalt.",
  "mrr": "Átlagos helyezés-mutató (Mean Reciprocal Rank): hányadik helyen van az első jó találat – 1. hely = 1, 2. hely = 0,5, 3. hely = 0,33. 1 = a jó találat mindig az első helyen van.",
  "útmutató-találat": "A kérdések hány százalékánál volt a találatok között legalább egy részlet a helyes útmutatóból (az oldaltól függetlenül).",
  "átl. találat": "Átlagosan hány forrást adott vissza a keresés kérdésenként.",
  "átl. idő ms": "A keresés átlagos ideje ezredmásodpercben (ms) – embedding, BM25, rerank együtt.",
  "csoport": "Mit hasonlít össze a sor: keresési módszert, chunkolást (szövegdarabolást) vagy embedding-modellt.",
  "változat": "A mért beállítás neve (pl. „hibrid + rerank” = vektoros + kulcsszavas keresés, majd újrarangsorolás).",

  // ---- Mérések · prompt-szint
  "eset": "Hány egykérdéses tesztesetet futtattunk a teljes rendszeren: válaszolós, „nincs benne”, elutasítandó és kétértelmű kérdéseket.",
  "elvárt viselkedés": "Mit kellett tennie: answer = válaszolni; not_found = kimondani, hogy nincs az útmutatókban; refuse = udvariasan elutasítani; clarify = visszakérdezni.",
  "viselkedés helyes": "Az esetek hány százalékában viselkedett jól: válaszolt, ha kellett; kimondta, ha nincs benne; elutasította a témán kívüli kérést; visszakérdezett, ha kétértelmű volt.",
  "helyesség (válaszolós)": "A válaszolós esetekben az elvárt kulcsinformációk hány százaléka szerepel a válaszban (egy „bíró” MI ellenőrzi). 1 = minden lényeges elem benne van.",
  "helyesség": "Az elvárt kulcsinformációk hány százaléka szerepel a válaszban (egy „bíró” MI ellenőrzi). 1 = minden lényeges elem benne van.",
  "kontextus-relevancia": "A válaszíró MI-nek forrásként átadott útmutató-részletek hány százaléka kapcsolódik ténylegesen a kérdéshez. Minél magasabb, annál kevesebb a „zaj”.",
  "hallucinációs arány": "A válaszok hány százalékában van olyan állítás, amit a források nem támasztanak alá (kitalált lépés vagy érték). A cél: 0 %.",
  "hallucináció": "A válaszok hány százalékában van olyan állítás, amit a források nem támasztanak alá. A cél: 0 %.",
  "hivatkozás helyes": "A válaszok hány százalékában léteznek a [n] jelvénnyel hivatkozott források, és a válaszolós eseteknél van legalább egy hivatkozás.",
  "első token p50 ms": "Az idő a kérdés elküldésétől a válasz első szaváig, ezredmásodpercben (ms). P50 = medián: a válaszok fele ennél gyorsabb.",
  "teljes idő p50 ms": "A teljes válasz elkészülésének ideje ezredmásodpercben (ms). P50 = medián: a válaszok fele ennél gyorsabb.",
  "költség / válasz $": "Egy válasz átlagos ára amerikai dollárban – a kérdés-átírás, a keresés, az újrarangsorolás és a válaszírás együtt.",

  // ---- Mérések · alkalmazás-szint
  "út": "Hány többkérdéses, szimulált felhasználói beszélgetést futtattunk (pl. „vízkőtelenítés → mennyi ideig tart?”).",
  "érvényes": "Az utak közül hány volt érvényes. Érvénytelen, ha a szimulált felhasználó maga írt útmutató-tartalmat – az ilyen kimarad az összesítésből.",
  "célelérés": "Az utak hány százalékában érte el a felhasználó a célját (egy bíró MI dönti el a teljes beszélgetés alapján).",
  "siker-lefedettség": "A cél ellenőrizhető elemeinek (pl. „a lépések”, „az időtartam”) hány százaléka teljesült átlagosan.",
  "elégedettség (1–5)": "Mennyire lenne elégedett a szimulált felhasználó 1–5 skálán – egy bíró MI becslése a beszélgetés alapján.",
  "válaszminőség (1–5)": "A válaszok minősége 1–5 skálán: érthető, lépésenkénti, tömör, megnevezi az eszközt, hivatkozik a forrásra.",
  "forráshű fordulók": "A beszélgetésekben a válaszok hány százaléka állt teljesen az útmutatókon – kitalált állítás nélkül.",
  "átl. forduló": "Átlagosan hány kérdés–válasz kör kellett egy beszélgetésben a cél eléréséig.",
  "első token p50 / p95 ms": `Az idő a kérdés elküldésétől a válasz első szaváig, ezredmásodpercben (ms). ${P50_P95}`,
  "teljes idő p50 / p95 ms": `A teljes válasz elkészülésének ideje, ezredmásodpercben (ms). ${P50_P95}`,
  "költség / út $": "Egy teljes többkérdéses beszélgetés átlagos ára amerikai dollárban.",
  "turns": "Hány kérdés–válasz kör volt a beszélgetésben.",
  "ended_by": "Hogyan ért véget: kész = a felhasználó elérte a célját; feladta = nem kapott segítséget; max_turns = elfogyott a megengedett körök száma.",
  "goal_achieved": "Elérte-e a felhasználó a célját (✔ / ✘).",
  "success_coverage": "A cél ellenőrizhető elemeinek hány százaléka teljesült (1 = mind).",
  "satisfaction": "Szimulált elégedettség 1–5 skálán.",
  "response_quality": "Válaszminőség 1–5 skálán.",
  "unsupported_claims": "Hány olyan állítás volt a válaszokban, amit a források nem támasztottak alá.",
  "ttft_p50_ms": "Medián idő az első szóig (ms).",
  "total_p50_ms": "Medián teljes válaszidő (ms).",
  "cost_usd": "A beszélgetés költsége amerikai dollárban.",

  // ---- Analitika / Visszajelzések / Monitoring / Dokumentumok
  "válasz": "Hány kérdésre válaszolt a rendszer a kiválasztott időszakban.",
  "válasz összesen": "Hány kérdésre válaszolt a rendszer összesen.",
  "„nem találtam” arány": "A kérdések hány százalékára nem volt forrás az útmutatókban. Ha magas (15 % fölött), valamelyik eszközhöz hiányzik vagy rosszul olvasódott be az útmutató.",
  "értékelt válasz": "Hány válaszra kattintottak a felhasználók 👍 vagy 👎 gombot.",
  "értékelt": "Hány válaszra kattintottak 👍 vagy 👎 gombot (zárójelben: az összes válasz hány százaléka).",
  "elégedettség (👍 arány)": "A pozitív (👍) értékelések aránya az összes értékelésen belül.",
  "elégedettség": "A pozitív (👍) értékelések aránya az összes értékelésen belül.",
  "👍 jó": "Hány válasz kapott pozitív értékelést.",
  "👎 nem jó": "Hány válasz kapott negatív értékelést – az okok és megjegyzések lent láthatók.",
  "első token (p50 / p95)": `Mennyi idő után jelenik meg a válasz első szava – ezt érzi a felhasználó várakozásnak. ${P50_P95}`,
  "teljes válaszidő (p50 / p95)": `A kérdés elküldésétől a válasz végéig eltelt idő. ${P50_P95}`,
  "átlagos költség / válasz": "Egy válasz átlagos ára amerikai dollárban, minden lépéssel együtt.",
  "chat-költség": "A felhasználói kérdések kiszolgálásának költsége az időszakban (átírás, keresés, rerank, válasz – és a mérések).",
  "indexelési költség": "Az útmutatók beolvasásának költsége (képleírás, beágyazás, metaadat) – egyszeri, új útmutatónál.",
  "token összesen": "A modellek által feldolgozott szövegmennyiség (1 token ≈ ¾ szó) – ez alapján számláznak a szolgáltatók.",
  "útmutató": "Hány útmutató kész (kérdezhető) / hány van feltöltve összesen.",
  "oldal": "Az útmutatók összesített oldalszáma.",
  "chunk (hibrid)": "Hány szövegrészletre (chunk) bontotta a rendszer az útmutatókat – a keresés ezek között keres.",
  "kép": "Hány kép jelenhet meg a válaszokban (a kiszűrt logók és apró képek nélkül).",
  "ocr-es útmutató": "Hány útmutatónak van beszkennelt (kép alapú) oldala, amit karakterfelismeréssel (OCR) kellett beolvasni.",
};

export function metricHelp(label: string): string | undefined {
  const key = label.trim().toLowerCase().replace(/@\d+/, "@k");
  return HELP[key];
}
