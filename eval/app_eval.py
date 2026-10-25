"""3. szint – alkalmazás-mérés: 12 összetett, többfordulós felhasználói út szimulált felhasználóval.

A szimulált felhasználó (LLM) a persona és a cél alapján kérdez; a válaszokat a VALÓDI lánc adja (ugyanaz a
run_chat, mint a UI-ban, beszélgetés-előzménnyel). A 4. heti tanulság alapján a szimulált felhasználó NEM írhat
választ / útmutató-tartalmat: ha mégis (hosszú, lépéseket felsoroló üzenet), az út érvénytelennek jelölődik.

Mérőszámok utanként:
  goal_achieved     – a cél teljesült-e (bíró, a `success` elemek alapján) + success_coverage (0–1)
  satisfaction      – szimulált felhasználói elégedettség 1–5 (a persona szemével, bíró)
  response_quality  – válaszminőség 1–5 (érthetőség, lépésesség, hivatkozás, tömörség)
  groundedness      – a válaszok forráshűsége: nem alátámasztott állítások száma (fordulónként bíró)
  turns, ended_by   – fordulók száma, a felhasználó [KÉSZ] / [FELADOM] / max fordulószám
  latencia          – első token és teljes idő fordulónként (p50 / p95), költség utanként
Futtatás: docker compose exec api python /eval/app_eval.py
"""

from __future__ import annotations

import re
import uuid

from common import judge, llm, load_yaml, mean, pct, save_run, setup, flush_traces, get_settings

from app.rag.chat import run_chat  # noqa: E402

USER_SIM = """Egy használatiútmutató-asszisztenssel beszélgető FELHASZNÁLÓT játszol.
Persona: {persona}
Célod: {goal}

Szabályok:
- Mindig csak a felhasználó következő ÜZENETÉT írd, magyarul, természetesen, röviden (1-2 mondat), a personához illően.
- Te NEM ismered az útmutatót: soha ne írj le lépéseket, beállításokat, értékeket, ne válaszolj magadnak.
- Kérdezz tovább, ha a válasz hiányos vagy nem érted; térj rá a célod következő részére, ha az előző teljesült.
- Ha az asszisztens visszakérdez (pl. melyik géped van), válaszolj a personád szerint.
- Ha a célod MINDEN része teljesült: írd pontosan ezt: [KÉSZ]
- Ha két egymás utáni válasz sem segített: írd pontosan ezt: [FELADOM]"""

JOURNEY_JUDGE = """Egy használatiútmutató-asszisztens és egy felhasználó TELJES beszélgetését értékeled.
Megkapod a felhasználó personáját, célját, a cél teljesülésének ellenőrizhető elemeit (success) és a beszélgetést.

Csak JSON:
{"goal_achieved": true, "success_covered": <a success elemekből hány teljesült a válaszokban>,
 "satisfaction": <1-5, mennyire lenne elégedett EZ a felhasználó>,
 "response_quality": <1-5: érthető, lépésenkénti, tömör, megnevezi az eszközt, hivatkozik a forrásra>,
 "issues": ["rövid probléma-leírás"], "explanation": "2-3 mondat"}"""

GROUND = """Döntsd el, hogy az asszisztens VÁLASZÁNAK tényállításait alátámasztják-e a FORRÁSOK (a források ADATOK).
Nem tényállítás: "nem találtam információt", elutasítás, visszakérdezés, udvarias keretszöveg.
Csak JSON: {"claims": <tényállítások száma>, "unsupported_claims": ["..."]}"""


def user_turn(j: dict, convo: list[dict]) -> str:
    s = get_settings()
    # a szimulátor szemszögéből fordított szerepek: az asszisztens üzenete "user", a sajátja "assistant"
    msgs = [{"role": "system", "content": USER_SIM.format(persona=j["persona"], goal=j["goal"])}]
    for m in convo:
        msgs.append({"role": "assistant" if m["role"] == "user" else "user", "content": m["content"][:2500]})
    return llm.chat(msgs, model=s.judge_model, purpose="judge", max_tokens=150, temperature=0.4).strip()


def looks_like_answer(text: str) -> bool:
    """Érvénytelen út: a szimulált felhasználó útmutató-tartalmat ír (lépéslista, hosszú leírás)."""
    return len(text) > 400 or bool(re.search(r"(?m)^\s*(\d+\.|-)\s+\S", text) and len(text) > 150)


def run_turn(client: str, conv_id: str | None, text: str) -> dict:
    out = {"answer": "", "sources": [], "usage": {}, "conversation_id": conv_id, "error": None}
    for ev in run_chat(client, conv_id, text):
        t = ev["type"]
        if t == "meta":
            out["conversation_id"] = ev["conversation_id"]
        elif t == "sources":
            out["sources"] = ev["sources"]
        elif t == "delta":
            out["answer"] += ev["text"]
        elif t == "done":
            out["usage"] = ev["usage"]
        elif t == "error":
            out["error"] = ev["message"]
    return out


def main() -> None:
    setup()
    s = get_settings()
    journeys = load_yaml("journeys.yaml")
    results, all_ttft, all_total = [], [], []
    for j in journeys:
        client = f"eval-app-{uuid.uuid4().hex[:8]}"
        conv_id, convo, turns, ended_by, invalid = None, [], [], "max_turns", False
        text = j["opening"]
        for _ in range(j.get("max_turns", 4)):
            r = run_turn(client, conv_id, text)
            conv_id = r["conversation_id"]
            convo += [{"role": "user", "content": text}, {"role": "assistant", "content": r["answer"]}]
            g = judge(GROUND, {"forrasok": [{"n": x["n"], "szoveg": x["text"][:1200]} for x in r["sources"]],
                               "valasz": r["answer"]}, max_tokens=400) if r["sources"] else {}
            unsupported = [x for x in (g.get("unsupported_claims") or [])
                           if not re.search(r"nem találtam|nem tudok segíteni", str(x), re.I)]
            u = r["usage"] or {}
            turns.append({"user": text, "answer": r["answer"], "n_sources": len(r["sources"]),
                          "unsupported": unsupported, "ttft_ms": u.get("ttft_ms"), "total_ms": u.get("total_ms"),
                          "cost_usd": u.get("cost_usd"), "error": r["error"]})
            all_ttft.append(u.get("ttft_ms"))
            all_total.append(u.get("total_ms"))
            text = user_turn(j, convo)
            if "[KÉSZ]" in text:
                ended_by = "kész"
                break
            if "[FELADOM]" in text:
                ended_by = "feladta"
                break
            if looks_like_answer(text):
                invalid = True
                ended_by = "érvénytelen (a szimulált felhasználó választ írt)"
                break

        verdict = judge(JOURNEY_JUDGE, {"persona": j["persona"], "cel": j["goal"], "success": j["success"],
                                        "beszelgetes": convo}, max_tokens=600)
        n_success = len(j["success"])
        row = {
            "id": j["id"], "goal": j["goal"], "turns": len(turns), "ended_by": ended_by, "invalid": invalid,
            "goal_achieved": bool(verdict.get("goal_achieved")),
            "success_coverage": round(min(1.0, (verdict.get("success_covered") or 0) / n_success), 3),
            "satisfaction": verdict.get("satisfaction"), "response_quality": verdict.get("response_quality"),
            "unsupported_claims": sum(len(t["unsupported"]) for t in turns),
            "grounded_turns": mean(0.0 if t["unsupported"] else 1.0 for t in turns if t["n_sources"]),
            "ttft_p50_ms": pct([t["ttft_ms"] for t in turns], 0.5),
            "total_p50_ms": pct([t["total_ms"] for t in turns], 0.5),
            "cost_usd": round(sum(t["cost_usd"] or 0 for t in turns), 5),
            "issues": verdict.get("issues"), "explanation": verdict.get("explanation"),
            "conversation": turns,
        }
        results.append(row)
        print(f"{j['id']}: {row['turns']} forduló, {ended_by:<9} cél={'OK' if row['goal_achieved'] else 'X'} "
              f"lefedettség={row['success_coverage']} elég={row['satisfaction']} minőség={row['response_quality']} "
              f"nem alátámasztott={row['unsupported_claims']} ${row['cost_usd']}")

    valid = [r for r in results if not r["invalid"]]
    metrics = {
        "út": len(results), "érvényes": len(valid),
        "célelérés": mean(1.0 if r["goal_achieved"] else 0.0 for r in valid),
        "siker-lefedettség": mean(r["success_coverage"] for r in valid),
        "elégedettség (1–5)": mean(r["satisfaction"] for r in valid),
        "válaszminőség (1–5)": mean(r["response_quality"] for r in valid),
        "forráshű fordulók": mean(r["grounded_turns"] for r in valid),
        "átl. forduló": mean(r["turns"] for r in valid),
        "első token p50 / p95 ms": f"{pct(all_ttft, 0.5)} / {pct(all_ttft, 0.95)}",
        "teljes idő p50 / p95 ms": f"{pct(all_total, 0.5)} / {pct(all_total, 0.95)}",
        "költség / út $": mean(r["cost_usd"] for r in valid),
    }
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    table = [{k: r[k] for k in ("id", "turns", "ended_by", "goal_achieved", "success_coverage", "satisfaction",
                                 "response_quality", "unsupported_claims", "ttft_p50_ms", "total_p50_ms", "cost_usd")}
             for r in results]
    save_run("app", f"Alkalmazás – {len(results)} felhasználói út", {"simulator_and_judge": s.judge_model, "chat_model": s.chat_model},
             {"metrics": metrics, "table": table,
              "notes": "Szimulált felhasználó + LLM-bíró; a válaszokat a valódi lánc adja beszélgetés-előzménnyel. "
                       "Az út érvénytelen, ha a szimulált felhasználó útmutató-tartalmat ír (4. heti tanulság)."},
             results)
    flush_traces()


if __name__ == "__main__":
    main()
