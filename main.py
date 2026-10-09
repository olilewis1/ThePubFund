import os
import sys
import math
import smtplib
import pandas as pd
import yfinance as yf
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date

# --- Configuration ---
PUBLISHED_BASE_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSuDaH4dwW9qbtKE2Zjm3V23KwEopaHaCiSiy9HbPpImILO8VpU_w8NmwmNSIFWEPuFv9eF-OoMCHME"
    "/pub?output=csv"
)
HOLDINGS_GID = "0"
WATCHLIST_GID = "273495191"
PINT_PRICE = 6.00

SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
# Comma-separated list: "alice@gmail.com,bob@outlook.com"
RECIPIENT_EMAILS = [
    e.strip()
    for e in os.environ.get("RECIPIENT_EMAILS", "oliverlewis1331@gmail.com").split(",")
    if e.strip()
]


# --- Data Fetching ---

def get_sheet_csv_url(gid):
    return f"{PUBLISHED_BASE_URL}&gid={gid}"


def fetch_holdings():
    df = pd.read_csv(get_sheet_csv_url(HOLDINGS_GID))
    df.columns = df.columns.str.strip()
    return df


def fetch_watchlist():
    df = pd.read_csv(get_sheet_csv_url(WATCHLIST_GID))
    df.columns = df.columns.str.strip()
    return df


def parse_price_str(price_str):
    """Parse strings like '£50', '$12.34', '1,234.56' into a float."""
    return float(str(price_str).strip().replace('£', '').replace('$', '').replace(',', ''))


def get_current_price(symbol):
    try:
        t = yf.Ticker(symbol)
        fi = t.fast_info
        price = fi.last_price
        if price is None or math.isnan(price) or price <= 0:
            return None
        # UK LSE stocks are quoted in GBX (pence) — convert to GBP
        currency = getattr(fi, 'currency', None)
        if currency == 'GBp':
            price /= 100
        return price
    except Exception as e:
        print(f"  [WARN] Price fetch failed for {symbol}: {e}")
        return None


def get_30day_trend(symbol):
    try:
        hist = yf.Ticker(symbol).history(period="1mo")
        if len(hist) < 2:
            return None
        start = float(hist["Close"].iloc[0])
        end = float(hist["Close"].iloc[-1])
        if math.isnan(start) or math.isnan(end) or start == 0:
            return None
        return ((end - start) / start) * 100
    except Exception as e:
        print(f"  [WARN] Trend fetch failed for {symbol}: {e}")
        return None


def get_top_news(symbol, n=2):
    try:
        news = yf.Ticker(symbol).news
        return (news or [])[:n]
    except Exception as e:
        print(f"  [WARN] News fetch failed for {symbol}: {e}")
        return []


# --- HTML Builders ---

def build_holdings_html(df):
    rows = ""
    total_pnl = 0.0

    for _, row in df.iterrows():
        symbol = str(row["Ticker"]).strip().upper()
        # Sheet columns: 'shares' (lowercase), 'price paid' (total cost as £XX)
        shares = float(row["shares"])
        total_cost = parse_price_str(row["price paid"])
        avg_price = total_cost / shares if shares > 0 else 0
        buyer = str(row.get("Who bought", "")).strip()

        print(f"  Fetching {symbol}...")
        current_price = get_current_price(symbol)
        # Fallback: try appending .L for LSE-listed stocks
        if current_price is None and not symbol.endswith(".L"):
            print(f"  Retrying as {symbol}.L ...")
            current_price = get_current_price(symbol + ".L")
        if current_price is None:
            continue

        current_value = current_price * shares
        pnl = current_value - total_cost
        total_pnl += pnl
        beer_roi = round(pnl / PINT_PRICE, 1)

        pnl_color = "#27ae60" if pnl >= 0 else "#e74c3c"
        sign = "+" if pnl >= 0 else ""
        beer_label = f"{sign}{beer_roi} pints {'🍺' if beer_roi >= 0 else '💸'}"
        buyer_badge = f' <span style="font-size:11px;color:#888">({buyer})</span>' if buyer else ''

        rows += f"""
                <tr>
                    <td><strong>{symbol}</strong>{buyer_badge}</td>
                    <td>{shares:.2f}</td>
                    <td>£{avg_price:.2f}</td>
                    <td>£{current_price:.2f}</td>
                    <td style="color:{pnl_color};font-weight:bold">{sign}£{pnl:,.2f}</td>
                    <td style="color:{pnl_color}">{beer_label}</td>
                </tr>"""

    total_color = "#27ae60" if total_pnl >= 0 else "#e74c3c"
    total_sign = "+" if total_pnl >= 0 else ""
    total_beers = round(total_pnl / PINT_PRICE, 1)

    return f"""
    <div class="section">
        <h2>📊 Current Portfolio</h2>
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Shares</th>
                    <th>Avg Price</th>
                    <th>Current Price</th>
                    <th>P&amp;L</th>
                    <th>🍺 Beer ROI</th>
                </tr>
            </thead>
            <tbody>{rows}
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="4"><strong>Total Portfolio P&amp;L</strong></td>
                    <td style="color:{total_color};font-weight:bold">{total_sign}£{total_pnl:,.2f}</td>
                    <td style="color:{total_color};font-weight:bold">{total_sign}{total_beers} pints 🍺</td>
                </tr>
            </tfoot>
        </table>
    </div>"""


def build_watchlist_html(df):
    html = '\n    <div class="section">\n        <h2>👀 Watchlist &amp; Sector Synopsis</h2>'

    for sector_name, sector_df in df.groupby("Sector"):
        html += f'\n        <div class="sector"><h3>🏭 {sector_name}</h3>'

        for _, row in sector_df.iterrows():
            symbol = str(row["Ticker"]).strip().upper()
            reason = str(row.get("Reason", "")).strip()

            print(f"  Fetching {symbol}...")
            current_price = get_current_price(symbol)
            trend = get_30day_trend(symbol)
            news_items = get_top_news(symbol)

            price_str = f"${current_price:.2f}" if current_price is not None else "N/A"

            if trend is not None:
                t_arrow = "▲" if trend >= 0 else "▼"
                t_color = "#27ae60" if trend >= 0 else "#e74c3c"
                trend_str = f'<span style="color:{t_color}">{t_arrow} {abs(trend):.1f}% (30d)</span>'
            else:
                trend_str = "<span>N/A</span>"

            news_html = ""
            for item in news_items:
                content = item.get("content", {})
                title = content.get("title") or item.get("title", "Read more")
                link = (
                    content.get("canonicalUrl", {}).get("url")
                    or item.get("link")
                    or "#"
                )
                news_html += f'<li><a href="{link}" style="color:#3498db;text-decoration:none">{title}</a></li>'

            html += f"""
            <div class="stock-card">
                <div class="stock-header">
                    <strong style="font-size:15px">{symbol}</strong>
                    <span class="price">{price_str}</span>
                    {trend_str}
                </div>
                <div class="reason">💡 <em>{reason}</em></div>
                <ul class="news-list">{news_html}</ul>
            </div>"""

        html += "\n        </div>"

    html += "\n    </div>"
    return html


def build_full_email(holdings_html, watchlist_html):
    date_str = datetime.now().strftime("%A, %d %B %Y")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    background-color: #f0f2f5;
    margin: 0; padding: 20px;
  }}
  .container {{
    max-width: 680px; margin: 0 auto;
    background: #ffffff; border-radius: 14px;
    overflow: hidden; box-shadow: 0 6px 30px rgba(0,0,0,0.12);
  }}
  .header {{
    background: linear-gradient(135deg, #0d1b2a 0%, #1b2838 60%, #1a3a5c 100%);
    color: #ffffff; padding: 36px 40px; text-align: center;
  }}
  .header h1 {{ margin: 0; font-size: 30px; letter-spacing: 1px; }}
  .header p  {{ margin: 8px 0 0; opacity: 0.75; font-size: 13px; }}
  .content   {{ padding: 32px 40px; }}
  .section   {{ margin-bottom: 44px; }}
  .section h2 {{
    color: #0d1b2a; font-size: 20px;
    border-bottom: 3px solid #1a3a5c; padding-bottom: 8px; margin-bottom: 16px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead tr {{ background: #1a3a5c; color: #ffffff; }}
  th, td {{ padding: 11px 10px; text-align: left; border-bottom: 1px solid #eee; }}
  tbody tr:nth-child(even) {{ background: #f8f9fb; }}
  tfoot tr {{ background: #e8edf3; }}
  .sector {{ margin-bottom: 28px; }}
  .sector h3 {{
    color: #1a3a5c; font-size: 15px; margin-bottom: 10px;
    background: #eef2f7; padding: 8px 14px; border-radius: 6px;
  }}
  .stock-card {{
    border: 1px solid #e0e6ec; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 10px;
  }}
  .stock-header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }}
  .price {{ color: #555; font-size: 13px; }}
  .reason {{ font-size: 12px; color: #777; margin-bottom: 6px; }}
  .news-list {{ margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.8; }}
  .footer {{
    background: #0d1b2a; color: #8899aa;
    text-align: center; padding: 20px; font-size: 11px;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🍺 The Pub Fund</h1>
    <p>Bi-Weekly Market Update &nbsp;·&nbsp; {date_str}</p>
  </div>
  <div class="content">
    {holdings_html}
    {watchlist_html}
  </div>
  <div class="footer">
    Cheers 🍺 &nbsp;·&nbsp; Data via Yahoo Finance &nbsp;·&nbsp; Delivered every other Sunday morning
  </div>
</div>
</body>
</html>"""


# --- Email Sender ---

def send_email(html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🍺 The Pub Fund — Update {datetime.now().strftime('%d %b %Y')}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = SENDER_EMAIL  # Sender sees their own address in To:
    msg["Bcc"] = ", ".join(RECIPIENT_EMAILS)  # All recipients hidden from each other
    msg.attach(MIMEText(html_content, "html"))

    all_recipients = list(dict.fromkeys([SENDER_EMAIL] + RECIPIENT_EMAILS))  # dedupe
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, all_recipients, msg.as_string())

    print(f"✅ Email sent to: {', '.join(all_recipients)}")


# --- Entry Point ---

def main():
    # Bi-weekly guard: only send every other Sunday, anchored to the
    # requested start date (Sunday 19 July 2026). Runs exactly every 14 days.
    # workflow_dispatch (manual trigger) bypasses this automatically
    # because GitHub sets GITHUB_EVENT_NAME=workflow_dispatch.
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    today = datetime.now()
    days_since_start = (today.date() - date(2026, 7, 19)).days
    if event == "schedule" and days_since_start % 14 != 0:
        print(f"⏭️  Skipping: {today.strftime('%A %d %b')} is an off week.")
        sys.exit(0)

    print("📥 Fetching Holdings from Google Sheets...")
    holdings_df = fetch_holdings()
    print(f"   {len(holdings_df)} positions found.")

    print("📥 Fetching Watchlist from Google Sheets...")
    watchlist_df = fetch_watchlist()
    print(f"   {len(watchlist_df)} watchlist items found.")

    print("📊 Building portfolio section...")
    holdings_html = build_holdings_html(holdings_df)

    print("👀 Building watchlist section...")
    watchlist_html = build_watchlist_html(watchlist_df)

    print("✉️  Composing and sending email...")
    email_html = build_full_email(holdings_html, watchlist_html)
    send_email(email_html)


if __name__ == "__main__":
    main()
