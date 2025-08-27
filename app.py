# app.py
import os
import asyncio

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from db import init_db, get_session, Product, Price, Daily
from scraper import schedule_hourly, compute_trend, is_heads_up, scrape_once
from datetime import datetime

app = Flask(__name__)
app.secret_key = "change-me"

init_db()
if not os.environ.get("CARDWATCH_DISABLE_SCHEDULER") and (
    os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug
):
    scheduler = schedule_hourly()

@app.route("/")
def index():
    s = get_session()
    try:
        products = s.query(Product).order_by(Product.name).all()
        model = []
        for p in products:
            trend = compute_trend(s, p.id)
            heads, now_low, avg7 = is_heads_up(s, p.id)

            # current (latest) and first (oldest) recorded prices
            latest = (s.query(Price)
                      .filter_by(product_id=p.id)
                      .order_by(Price.ts.desc())
                      .first())
            first  = (s.query(Price)
                      .filter_by(product_id=p.id)
                      .order_by(Price.ts.asc())
                      .first())

            model.append({
                "id": p.id,
                "name": p.name,
                "country": p.country,
                "url": p.url,
                "enabled": bool(p.is_enabled),

                "trend": trend,
                "heads": heads,
                "avg7": avg7,

                # new fields
                "current_low": latest.low if latest else None,
                "first_low": first.low if first else None,

                "last_ts": latest.ts.strftime("%Y-%m-%d %H:%M") if latest else None,
            })
        return render_template("index.html", products=model)
    finally:
        s.close()

@app.route("/product/<int:pid>")
def product(pid):
    s = get_session()
    try:
        p = s.get(Product, pid)
        if not p:
            return "Not found", 404
        return render_template("product.html", product=p)
    finally:
        s.close()


@app.route("/api/product/<int:pid>/series")
def api_series(pid):
    s = get_session()
    try:
        points = s.query(Price).filter_by(product_id=pid).order_by(Price.ts).all()
        return jsonify([{"t": pr.ts.isoformat(), "low": pr.low, "avg5": pr.avg5} for pr in points])
    finally:
        s.close()

@app.route("/api/product/<int:pid>/daily")
def api_daily(pid):
    s = get_session()
    try:
        points = s.query(Daily).filter_by(product_id=pid).order_by(Daily.day).all()
        return jsonify([{"d": d.day.isoformat(), "low": d.low, "avg": d.avg} for d in points])
    finally:
        s.close()

@app.route("/add", methods=["POST"])
def add():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    country = request.form.get("country", "").strip()
    if not (name and url and country):
        flash("Please provide name, url, and country.")
        return redirect(url_for("index"))
    s = get_session()
    pid = None
    try:
        p = Product(name=name, url=url, country=country)
        s.add(p)
        s.commit()
        pid = p.id
        flash("Added.")
    except Exception as e:
        s.rollback()
        flash(f"Error: {e}")
    finally:
        s.close()
    if pid:
        try:
            asyncio.run(scrape_once([pid]))
        except Exception as e:
            print(f"[app] Error scraping new product {pid}: {e}")
    return redirect(url_for("index"))

@app.route("/edit/<int:pid>", methods=["GET", "POST"])
def edit(pid):
    s = get_session()
    try:
        p = s.get(Product, pid)
        if not p:
            return "Not found", 404
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            url = request.form.get("url", "").strip()
            country = request.form.get("country", "").strip()
            if not (name and url and country):
                flash("Please provide name, url, and country.")
            else:
                try:
                    p.name = name
                    p.url = url
                    p.country = country
                    s.commit()
                    flash("Updated.")
                    return redirect(url_for("index"))
                except Exception as e:
                    s.rollback()
                    flash(f"Error: {e}")
        return render_template("edit.html", product=p)
    finally:
        s.close()

@app.route("/toggle/<int:pid>")
def toggle(pid):
    s = get_session()
    try:
        p = s.query(Product).get(pid)
        if not p: return "Not found", 404
        p.is_enabled = 0 if p.is_enabled else 1
        s.commit()
        return redirect(url_for("index"))
    finally:
        s.close()

@app.route("/delete/<int:pid>", methods=["POST"])
def delete(pid):
    s = get_session()
    try:
        p = s.query(Product).get(pid)
        if not p: return "Not found", 404
        s.delete(p)
        s.commit()
        flash("Deleted.")
        return redirect(url_for("index"))
    finally:
        s.close()

if __name__ == "__main__":
    app.run(debug=True)
