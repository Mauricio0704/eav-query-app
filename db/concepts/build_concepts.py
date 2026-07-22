#!/usr/bin/env python3
"""
Genera el mapeo de CONCEPTOS comparables entre olas (Fase 2).

Lee `data/encuesta_multianual.duckdb` (todas las olas cargadas) y escribe
`db/concepts/concepts.csv` + `concept_members.csv`, que `build_db.py` carga.

Empareja preguntas equivalentes entre años por:
  - Semilla: los atributos verificados (respondent_attributes.attribute, que es
    un nombre estable entre años) → conceptos ciertos.
  - Texto: similitud (difflib) con best-match mutuo entre pares de olas.
Y determina si son COMPARABLES (las opciones coinciden por CÓDIGO entre años):
solo esos se cargan (habilitan "group_by=year"). Los de opciones drift se omiten
(Fase 2b). Ver data/concept_review/ para el detalle revisado con el usuario.

Uso:  .venv/bin/python3 db/concepts/build_concepts.py
"""

import re
import csv
import unicodedata
import difflib
from pathlib import Path
from collections import defaultdict, Counter

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "encuesta_multianual.duckdb"
OUT = ROOT / "db" / "concepts"

SENT = {7777, 8888, 9999}  # No aplica / No sabe / No contesta (0 y 5555 son opciones reales)
TH = 0.62  # umbral de similitud de texto

# Falsos positivos confirmados con el usuario (medidas distintas mal emparejadas).
FALSE_POS_PAIRS = [
    {"total_min_trabajo_rem", "total_min_trabajo_rem_y_norem"},
    {"tiempo_regreso", "tiempo_total_traslado"},
]
# Atributos que NO se marcan comparables (rangos/códigos por confirmar en v2b).
ATTR_NON_COMPARABLE = {"ingreso"}


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\b(cp|p)\s*\d+(\s*[_\s]\s*\d+)*\b", " ", t)
    t = re.sub(r"\bnombre del estudiante\b|\bnombre\b|\(nombre\)|\[[^\]]*\]", " ", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _sim(a, b):
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / max(len(ta | tb), 1)
    return 0.5 * seq + 0.5 * jac


def main():
    con = duckdb.connect(str(DB), read_only=True)
    waves = [r[0] for r in con.execute("SELECT wave_id FROM waves ORDER BY wave_id").fetchall()]
    Q, OPTS = {}, defaultdict(dict)
    for w in waves:
        for qid, txt, qt in con.execute(
            "SELECT q_id,q_text,q_type FROM questions WHERE wave_id=?", [w]
        ).fetchall():
            Q[(w, qid)] = {"wave": w, "qid": qid, "text": txt or "", "type": qt or ""}
        for qid, oid, lab in con.execute(
            "SELECT question_id,option_id,option_label FROM options WHERE wave_id=?", [w]
        ).fetchall():
            OPTS[(w, qid)][oid] = lab or ""
    attr_seed = defaultdict(dict)
    for w, attr, qid in con.execute(
        "SELECT DISTINCT wave_id,attribute,question_id FROM respondent_attributes"
    ).fetchall():
        attr_seed[attr][w] = qid
    con.close()

    def opts_status(nodes):
        cats = [n for n in nodes if Q[n]["type"] == "categorica" and OPTS[n]]
        if len(cats) < 2:
            return "na"
        codes = [frozenset(o for o in OPTS[n] if o not in SENT) for n in cats]
        labs = lambda n: {o: _norm(OPTS[n][o]) for o in OPTS[n] if o not in SENT}
        if all(s == codes[0] for s in codes):
            base = labs(cats[0])
            return "match" if all(labs(n) == base for n in cats[1:]) else "relabel?"
        inter = set.intersection(*[set(s) for s in codes])
        uni = set().union(*[set(s) for s in codes])
        return "code_partial" if len(inter) / max(len(uni), 1) >= 0.6 else "code_diff"

    # --- best-match mutuo entre pares de olas (excluye nodos-atributo) ---
    attr_nodes = {(w, q) for wq in attr_seed.values() for w, q in wq.items() if (w, q) in Q}
    pool = defaultdict(list)
    for (w, q) in Q:
        if (w, q) not in attr_nodes:
            pool[w].append((w, q))

    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(waves)):
        for j in range(i + 1, len(waves)):
            wa, wb = waves[i], waves[j]
            AB, BA = {}, {}
            for na in pool[wa]:
                bb, bs = None, 0
                for nb in pool[wb]:
                    s = _sim(Q[na]["text"], Q[nb]["text"])
                    if s > bs:
                        bs, bb = s, nb
                if bb and bs >= TH:
                    AB[na] = bb
            for nb in pool[wb]:
                ba, bs = None, 0
                for na in pool[wa]:
                    s = _sim(Q[nb]["text"], Q[na]["text"])
                    if s > bs:
                        bs, ba = s, na
                if ba and bs >= TH:
                    BA[nb] = ba
            for na, nb in AB.items():
                if BA.get(nb) == na:
                    union(na, nb)

    clusters = defaultdict(list)
    for n in [x for ws in pool.values() for x in ws]:
        clusters[find(n)].append(n)

    def is_false_pos(nodes):
        ids = {q for _, q in nodes}
        return any(pair <= ids for pair in FALSE_POS_PAIRS)

    concepts, members = [], []
    concept_nodes = {}  # cid -> {"chosen": [...], "all": [...], "ctype": ...}

    def _code_key(n):
        """Firma de códigos (sin centinelas) de una pregunta categórica; None si
        es numérica en esa ola (comparable con cualquier subconjunto)."""
        if Q[n]["type"] == "categorica" and OPTS[n]:
            return frozenset(o for o in OPTS[n] if o not in SENT)
        return None

    def emit(cid, label, nodes, is_attr):
        if len({w for w, _ in nodes}) < 2:
            return
        if any(len(v) > 1 for v in _perwave(nodes).values()):
            return  # >1 pregunta del mismo año en el concepto (ambiguo)
        if not is_attr and is_false_pos(nodes):
            return
        if is_attr and label in ATTR_NON_COMPARABLE:
            return

        types = {Q[n]["type"] for n in nodes}
        ctype = "numerica" if "numerica" in types else "categorica"

        # Comparabilidad por SUBCONJUNTO: quedarse con las olas cuyas opciones
        # coinciden por código (el grupo más grande). Las olas numéricas (None)
        # se suman a cualquier grupo. Así una recodificación en una ola (p. ej.
        # sexo 1/2 en 2022 vs 0/1) no tumba la comparación de las demás.
        groups = defaultdict(list)
        for n in nodes:
            groups[_code_key(n)].append(n)
        cat_groups = {k: v for k, v in groups.items() if k is not None}
        if cat_groups:
            best = max(cat_groups.values(), key=lambda v: len({Q[n]["wave"] for n in v}))
            chosen = best + groups.get(None, [])
        else:
            chosen = nodes  # todas numéricas
        chosen = list({(Q[n]["wave"]): n for n in chosen}.values())  # 1 por ola

        if len({Q[n]["wave"] for n in chosen}) < 2:
            return
        om = opts_status(chosen)
        if om not in ("match", "relabel?", "na"):
            return
        concepts.append(
            {"concept_id": cid, "label": label[:80], "q_type": ctype,
             "comparable": True, "n_waves": len({Q[n]["wave"] for n in chosen}), "opts": om}
        )
        for n in chosen:
            members.append({"concept_id": cid, "wave_id": Q[n]["wave"], "q_id": Q[n]["qid"]})
        concept_nodes[cid] = {"chosen": chosen, "all": nodes, "ctype": ctype}

    def _perwave(nodes):
        d = defaultdict(list)
        for n in nodes:
            d[Q[n]["wave"]].append(Q[n]["qid"])
        return d

    for attr, wq in sorted(attr_seed.items()):
        emit("attr_" + attr, attr, [(w, q) for w, q in wq.items() if (w, q) in Q], True)
    for k, (_, nodes) in enumerate(clusters.items(), 1):
        emit(f"c{k:03d}", _norm(Q[sorted(nodes)[0]]["text"]) or f"concepto {k}", nodes, False)

    # --- Catálogo canónico + mapa de opciones (IDENTIDAD para el subconjunto
    #     alineado) + propuestas de RECODE para las olas excluidas ---------------
    def _latest(nodes):
        return max(nodes, key=lambda n: Q[n]["wave"])

    catalog, opt_map, recode_review = [], [], []
    for cid, info in concept_nodes.items():
        chosen = info["chosen"]
        cat_chosen = [n for n in chosen if Q[n]["type"] == "categorica" and OPTS[n]]
        if not cat_chosen:
            continue
        # códigos canónicos = los del subconjunto alineado (todos comparten set)
        canon_codes = sorted(OPTS[_latest(cat_chosen)].keys())
        lab_src = _latest(cat_chosen)
        for oid in canon_codes:
            catalog.append({"concept_id": cid, "concept_option_id": f"{cid}:{oid}",
                            "label": OPTS[lab_src].get(oid, str(oid)), "sort_order": oid})
        # mapa identidad para cada miembro categórico elegido
        for n in cat_chosen:
            for oid in OPTS[n]:
                opt_map.append({"concept_id": cid, "wave_id": Q[n]["wave"], "q_id": Q[n]["qid"],
                                "option_id": oid, "concept_option_id": f"{cid}:{oid}"})
        # --- propuestas de recode: olas excluidas con MISMO nº de opciones ---
        canon_real = [o for o in canon_codes if o not in SENT]
        excluded = [n for n in info["all"] if n not in chosen
                    and Q[n]["type"] == "categorica" and OPTS[n]]
        for e in excluded:
            e_real = sorted(o for o in OPTS[e] if o not in SENT)
            c_real = sorted(canon_real)
            if len(e_real) != len(c_real) or not e_real:
                continue  # no es recode "obvio" (cambió el nº de opciones)
            # alinear por orden de código
            for e_oid, c_oid in zip(e_real, c_real):
                recode_review.append({
                    "concept_id": cid, "wave_id": Q[e]["wave"], "q_id": Q[e]["qid"],
                    "option_id": e_oid, "option_label": OPTS[e][e_oid],
                    "canon_option_id": f"{cid}:{c_oid}",
                    "canon_label": OPTS[lab_src].get(c_oid, str(c_oid)),
                    "aprobar": "",
                })
            # centinelas → identidad (mismo código canónico si existe)
            for s in OPTS[e]:
                if s in SENT:
                    recode_review.append({
                        "concept_id": cid, "wave_id": Q[e]["wave"], "q_id": Q[e]["qid"],
                        "option_id": s, "option_label": OPTS[e][s],
                        "canon_option_id": f"{cid}:{s}", "canon_label": OPTS[e][s],
                        "aprobar": "",
                    })

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "concepts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["concept_id", "label", "q_type", "comparable", "n_waves", "opts"])
        w.writeheader()
        w.writerows(concepts)
    with open(OUT / "concept_members.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["concept_id", "wave_id", "q_id"])
        w.writeheader()
        w.writerows(members)
    with open(OUT / "concept_options.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["concept_id", "concept_option_id", "label", "sort_order"])
        w.writeheader()
        w.writerows(catalog)
    with open(OUT / "concept_option_map.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["concept_id", "wave_id", "q_id", "option_id", "concept_option_id"])
        w.writeheader()
        w.writerows(opt_map)
    # merge de recodes APROBADOS (si existe el archivo confirmado): se suman al
    # mapa y a los miembros para reincluir esas olas en la comparación.
    approved = OUT / "concept_recodes_approved.csv"
    n_recodes = 0
    if approved.exists():
        with open(approved) as f:
            for r in csv.DictReader(f):
                opt_map.append({"concept_id": r["concept_id"], "wave_id": r["wave_id"],
                                "q_id": r["q_id"], "option_id": int(r["option_id"]),
                                "concept_option_id": r["concept_option_id"]})
                members.append({"concept_id": r["concept_id"], "wave_id": r["wave_id"], "q_id": r["q_id"]})
                n_recodes += 1
        # reescribir map + members con los recodes ya integrados, deduplicando members
        seen = set(); dedup = []
        for m in members:
            k = (m["concept_id"], m["wave_id"], m["q_id"])
            if k not in seen:
                seen.add(k); dedup.append(m)
        with open(OUT / "concept_members.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["concept_id", "wave_id", "q_id"]); w.writeheader(); w.writerows(dedup)
        with open(OUT / "concept_option_map.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["concept_id", "wave_id", "q_id", "option_id", "concept_option_id"]); w.writeheader(); w.writerows(opt_map)
    with open(OUT / "concept_recodes_proposed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["concept_id", "wave_id", "q_id", "option_id",
                                          "option_label", "canon_option_id", "canon_label", "aprobar"])
        w.writeheader()
        w.writerows(recode_review)

    print(f"catálogo concept_options: {len(catalog)} | mapa opciones: {len(opt_map)} | recodes aplicados: {n_recodes}")
    print(f"recodes PROPUESTOS (revisar): {len({(r['concept_id'],r['wave_id']) for r in recode_review})} conceptos-ola en concept_recodes_proposed.csv")
    print(f"olas: {waves}")
    print(f"conceptos comparables: {len(concepts)}  (members={len(members)})")
    print(f"  por #olas: {dict(Counter(c['n_waves'] for c in concepts))}")
    print(f"  por tipo:  {dict(Counter(c['q_type'] for c in concepts))}")
    print(f"  atributos: {[c['label'] for c in concepts if c['concept_id'].startswith('attr_')]}")


if __name__ == "__main__":
    main()
