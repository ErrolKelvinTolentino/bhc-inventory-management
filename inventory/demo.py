"""Session-scoped sample inventory. Never writes fixtures to Supabase."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid4, uuid5


def uid(name):
    return str(uuid5(NAMESPACE_DNS, f"bhc.preview.{name}"))


def seed(today):
    categories = [
        ("Analgesics", "medicine"), ("Antibiotics", "medicine"),
        ("Antihistamines", "medicine"), ("Maintenance", "medicine"),
        ("Respiratory", "medicine"), ("Vitamins & supplements", "medicine"),
        ("Rehydration", "medicine"), ("Protective equipment", "supply"),
        ("Wound care", "supply"), ("Consumables", "supply"),
    ]
    rows = [
        ("Paracetamol", "500 mg", "Tablet", "Analgesics", 1240, 200, 270, "Biogesic"),
        ("Amoxicillin", "500 mg", "Capsule", "Antibiotics", 48, 100, 19, "Generic"),
        ("Cetirizine", "10 mg", "Tablet", "Antihistamines", 360, 100, 180, "Generic"),
        ("Losartan", "50 mg", "Tablet", "Maintenance", 620, 100, 240, "Generic"),
        ("Metformin", "500 mg", "Tablet", "Maintenance", 840, 200, 210, "Generic"),
        ("Salbutamol", "2 mg", "Tablet", "Respiratory", 180, 50, 150, "Generic"),
        ("Ascorbic acid", "500 mg", "Tablet", "Vitamins & supplements", 720, 100, 200, "Vitamin C"),
        ("Ibuprofen", "200 mg", "Tablet", "Analgesics", 240, 100, 190, "Generic"),
        ("Oral rehydration salts", "20.5 g", "Sachet", "Rehydration", 72, 30, 12, "ORS"),
        ("Ferrous sulfate", "325 mg", "Tablet", "Vitamins & supplements", 0, 50, 240, "Generic"),
        ("Amlodipine", "5 mg", "Tablet", "Maintenance", 540, 100, 260, "Generic"),
        ("Co-trimoxazole", "800 / 160 mg", "Tablet", "Antibiotics", 96, 50, 120, "Generic"),
        ("Examination gloves", "Medium · powder-free", "Pair", "Protective equipment", 200, 300, None, "Non-sterile"),
        ("Sterile gauze", "4 × 4 in", "Pack", "Wound care", 860, 100, 240, "8-ply"),
        ("Disposable syringe", "3 mL · with needle", "Piece", "Consumables", 540, 100, 360, "Sterile"),
        ("Isopropyl alcohol", "70% · 500 mL", "Bottle", "Consumables", 84, 20, 200, "Antiseptic"),
        ("Surgical face masks", "3-ply · ear loop", "Box", "Protective equipment", 36, 10, 24, "50 pieces / box"),
        ("Cotton balls", "100 g", "Pack", "Wound care", 240, 100, None, "Absorbent"),
        ("Adhesive tape", "1 in × 10 yd", "Roll", "Wound care", 36, 12, None, "Microporous"),
    ]
    model = {
        "facility": {"id": uid("facility"), "name": "San Isidro Health Center", "timezone": "Asia/Manila", "near_expiry_days": 30},
        "user": {"id": uid("ana"), "name": "Ana Mendoza", "role": "admin", "email": "ana@example.test"},
        "members": [
            {"user_id": uid("ana"), "name": "Ana Mendoza", "role": "admin", "is_active": True},
            {"user_id": uid("rafael"), "name": "Rafael Santos", "role": "staff", "is_active": True},
            {"user_id": uid("mariel"), "name": "Mariel Cruz", "role": "staff", "is_active": True},
        ],
        "categories": [{"id": uid(n), "name": n, "item_type": t} for n, t in categories],
        "items": [], "batches": [], "transactions": [], "audit_events": [],
    }
    for index, (name, strength, form, category, quantity, threshold, days, brand) in enumerate(rows):
        item_id = uid(name)
        kind = "medicine" if index < 12 else "supply"
        model["items"].append({
            "id": item_id, "facility_id": uid("facility"), "code": f"{'MED' if index < 12 else 'SUP'}-{index + 1:03}",
            "name": name, "strength": strength if kind == "medicine" else "",
            "dosage_form": form if kind == "medicine" else "", "specification": strength if kind == "supply" else "",
            "generic_name": name if kind == "medicine" else "", "brand": brand,
            "unit": form.lower(), "item_type": kind, "category_id": uid(category),
            "expiry_required": days is not None, "low_stock_threshold": threshold,
            "description": "", "is_archived": False,
        })
        if quantity:
            model["batches"].append({"id": uid(name + ".batch"), "item_id": item_id,
                "batch_number": f"{'MED' if kind == 'medicine' else 'SUP'}26-{index + 101}",
                "expiry_date": (today + timedelta(days=days)).isoformat() if days is not None else None,
                "quantity_on_hand": quantity, "created_at": f"{today - timedelta(days=14)}T08:00:00+08:00"})
    model["batches"].append({"id": uid("expired.batch"), "item_id": uid("Co-trimoxazole"),
        "batch_number": "MED25-086", "expiry_date": (today - timedelta(days=8)).isoformat(),
        "quantity_on_hand": 24, "created_at": f"{today - timedelta(days=14)}T08:00:00+08:00"})
    # Seed a consistent ledger: opening receipts include the following issues.
    issues = [("Paracetamol", 120, 5), ("Examination gloves", 40, 5),
        ("Metformin", 80, 4), ("Paracetamol", 90, 3), ("Disposable syringe", 60, 3),
        ("Cetirizine", 30, 2), ("Examination gloves", 60, 2), ("Paracetamol", 80, 1),
        ("Amoxicillin", 24, 1), ("Paracetamol", 60, 0), ("Sterile gauze", 40, 0),
        ("Amoxicillin", 12, 0)]
    for batch in model["batches"]:
        outgoing = sum(q for name, q, _ in issues if uid(name + ".batch") == batch["id"])
        current = batch["quantity_on_hand"]
        batch["quantity_on_hand"] = 0
        post_stock(model, {"p_item_id": batch["item_id"], "p_transaction_type": "receipt",
            "p_quantity": current + outgoing, "p_idempotency_key": str(uuid4()), "p_batch_id": batch["id"],
            "p_source_destination": "Municipal health office", "p_reference_number": "DEL-2026-014"},
            today, occurred_at=f"{today - timedelta(days=6)}T08:30:00+08:00")
    for n, (name, quantity, days_ago) in enumerate(issues):
        post_stock(model, {"p_item_id": uid(name), "p_transaction_type": "issue", "p_quantity": quantity,
            "p_idempotency_key": str(uuid4()), "p_source_destination": "Outpatient services"}, today,
            occurred_at=f"{today - timedelta(days=days_ago)}T{9 + n % 3:02}:{(n * 7 + 10) % 60:02}:00+08:00")
    return model


def audit(model, table, old, new, now):
    model["audit_events"].insert(0, {"id": str(uuid4()), "table_name": table,
        "action": "UPDATE" if old else "INSERT", "actor_name": model["user"]["name"],
        "occurred_at": now, "old_data": deepcopy(old), "new_data": deepcopy(new)})


def snapshot(model, today):
    data = deepcopy(model)
    for item in data["items"]:
        batches = [b for b in data["batches"] if b["item_id"] == item["id"]]
        usable = [b for b in batches if not b["expiry_date"] or b["expiry_date"] >= today.isoformat()]
        expired = [b for b in batches if b["expiry_date"] and b["expiry_date"] < today.isoformat()]
        soon = [b for b in usable if b["expiry_date"] and b["expiry_date"] <= (today + timedelta(days=model["facility"]["near_expiry_days"])).isoformat()]
        item["physical_quantity"] = sum(b["quantity_on_hand"] for b in batches)
        item["usable_quantity"] = sum(b["quantity_on_hand"] for b in usable)
        item["expired_quantity"] = sum(b["quantity_on_hand"] for b in expired)
        item["near_expiry_quantity"] = sum(b["quantity_on_hand"] for b in soon)
        item["stock_status"] = "out_of_stock" if not item["usable_quantity"] else "low_stock" if item["usable_quantity"] <= item["low_stock_threshold"] else "in_stock"
    for batch in data["batches"]:
        batch["expiry_status"] = "expired" if batch["expiry_date"] and batch["expiry_date"] < today.isoformat() else "near_expiry" if batch["expiry_date"] and batch["expiry_date"] <= (today + timedelta(days=model["facility"]["near_expiry_days"])).isoformat() else "usable"
    data["transactions"].sort(key=lambda t: t["occurred_at"], reverse=True)
    for tx in data["transactions"]:
        tx.pop("request_payload", None)
    return data


def post_stock(model, params, today, occurred_at=None):
    kind = params.get("p_transaction_type")
    quantity = params.get("p_quantity")
    item = next((i for i in model["items"] if i["id"] == params.get("p_item_id")), None)
    if not item or item["is_archived"]:
        raise ValueError("Choose an active inventory item.")
    if kind not in ("receipt", "issue", "adjustment", "disposal"):
        raise ValueError("Choose a valid stock movement.")
    if type(quantity) is not int or quantity < 0 or (kind != "adjustment" and quantity == 0):
        raise ValueError("Enter a whole number greater than zero.")
    if not params.get("p_idempotency_key"):
        raise ValueError("An operation key is required.")
    reason = str(params.get("p_reason") or "").strip()
    correction = params.get("p_corrects_transaction_id")
    if (kind in ("adjustment", "disposal") or correction) and model["user"]["role"] != "admin":
        raise PermissionError("An administrator is required for this action.")
    if (kind in ("adjustment", "disposal") or correction) and not reason:
        raise ValueError("Add a reason for this stock movement.")
    if correction and not any(t["id"] == correction and t["item_id"] == item["id"] for t in model["transactions"]):
        raise ValueError("The correction must reference this item's history.")
    previous = next((t for t in model["transactions"] if t["idempotency_key"] == params["p_idempotency_key"]), None)
    if previous:
        if previous["request_payload"] != params:
            raise ValueError("This operation key was already used for another request.")
        return previous["id"]
    batch_id = params.get("p_batch_id")
    batches = [b for b in model["batches"] if b["item_id"] == item["id"]]
    batch = next((b for b in batches if b["id"] == batch_id), None)
    if batch_id and not batch:
        raise ValueError("That batch does not belong to this item.")
    if (kind != "receipt" or batch_id) and (params.get("p_batch_number") or params.get("p_expiry_date")):
        raise ValueError("Choose an existing batch or enter new batch details, not both.")
    if kind in ("adjustment", "disposal") and not batch:
        raise ValueError("Choose the batch to update.")
    if kind == "receipt" and not batch:
        lot = str(params.get("p_batch_number") or "").strip()
        expiry = params.get("p_expiry_date") or None
        if not lot:
            raise ValueError("Enter a batch or lot number.")
        if item["expiry_required"] and not expiry:
            raise ValueError("This item requires an expiry date.")
        if expiry:
            try:
                date.fromisoformat(expiry)
            except ValueError as error:
                raise ValueError("Enter a valid expiry date.") from error
        batch = next((b for b in batches if b["batch_number"] == lot and b["expiry_date"] == expiry), None)
        if not batch:
            batch = {"id": str(uuid4()), "item_id": item["id"], "batch_number": lot,
                "expiry_date": expiry, "quantity_on_hand": 0, "created_at": occurred_at or datetime.now().astimezone().isoformat()}
            model["batches"].append(batch)
    allocations = []
    if kind == "issue" and not batch:
        remaining = quantity
        for candidate in sorted(batches, key=lambda b: (b["expiry_date"] or "9999", b["created_at"], b["id"])):
            if candidate["expiry_date"] and candidate["expiry_date"] < today.isoformat():
                continue
            take = min(remaining, candidate["quantity_on_hand"])
            if take:
                allocations.append((candidate, -take))
                remaining -= take
            if not remaining:
                break
        if remaining:
            raise ValueError("There isn't enough usable stock for this issue.")
    else:
        change = quantity - batch["quantity_on_hand"] if kind == "adjustment" else quantity if kind == "receipt" else -quantity
        if not change:
            raise ValueError("The counted quantity matches the current balance.")
        if kind == "issue" and batch["expiry_date"] and batch["expiry_date"] < today.isoformat():
            raise ValueError("Expired stock cannot be issued.")
        if batch["quantity_on_hand"] + change < 0:
            raise ValueError("There isn't enough stock in this batch.")
        allocations.append((batch, change))
    tx_id = str(uuid4())
    lines = []
    for target, delta in allocations:
        before = target["quantity_on_hand"]
        target["quantity_on_hand"] += delta
        lines.append({"id": str(uuid4()), "batch_id": target["id"], "batch_number": target["batch_number"],
            "expiry_date": target["expiry_date"], "quantity_change": delta, "balance_before": before,
            "balance_after": target["quantity_on_hand"]})
    model["transactions"].append({"id": tx_id, "item_id": item["id"], "transaction_type": kind,
        "quantity_change": sum(line["quantity_change"] for line in lines), "reason": reason,
        "source_destination": params.get("p_source_destination"), "reference_number": params.get("p_reference_number"),
        "corrects_transaction_id": correction, "actor_id": model["user"]["id"], "actor_name": model["user"]["name"],
        "item_name": item["name"], "item_code": item["code"], "unit": item["unit"],
        "occurred_at": occurred_at or datetime.now().astimezone().isoformat(),
        "idempotency_key": params["p_idempotency_key"], "request_payload": deepcopy(params), "lines": lines})
    return tx_id
