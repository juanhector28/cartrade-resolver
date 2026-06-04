def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/crautos.db")
    ap.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="segundos entre requests (default 1.0)"
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max detalles a scrapear"
    )
    ap.add_argument("--ids-only", action="store_true")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    if args.export:
        export_csv(conn)
        return

    session = make_session()

    print("== Fase 1: recolectando IDs del listado ==")

    # Paginacion por el campo 'p' del form (verificado). collect_ids hace
    # el barrido completo en una sola sesion.
    ids = collect_ids(session, args.delay)

    print(f"Total IDs encontrados: {len(ids)}")

    with open("/tmp/crautos_ids.txt", "w") as f:
        f.write("\n".join(sorted(ids)))

    if args.ids_only:
        return

    done = {
        str(r[0])
        for r in conn.execute("SELECT id FROM cars")
    }

    pending = sorted(ids - done)

    if args.limit:
        pending = pending[:args.limit]

    print(
        f"== Fase 2: {len(pending)} detalles pendientes "
        f"({len(done)} ya en DB) =="
    )

    for i, car_id in enumerate(pending, 1):
        r = fetch(
            session,
            "GET",
            DETAIL_URL,
            params={"c": car_id}
        )

        if r:
            try:
                save_car(
                    conn,
                    parse_detail(r.text, car_id)
                )
            except Exception as e:
                print(f"  [parse err] id={car_id}: {e}")

        if i % 50 == 0:
            print(
                f"  {i}/{len(pending)} "
                f"({datetime.now():%H:%M:%S})"
            )

        time.sleep(
            args.delay + random.uniform(0, 0.4)
        )

    print("Listo. Ejecuta con --export para generar el CSV.")
