"""FastBooking landing, tenant onboarding, and module configuration."""

from __future__ import annotations

import datetime
import hashlib
import json
import secrets
from decimal import Decimal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fasthtml.common import *
from sqlalchemy import func, select
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, RedirectResponse

from app.auth import google
from app.auth.access import ADMIN_ROLE, can_configure_products
from app.db.engine import async_session_factory
from app.db.models import User
from app.db.platform_models import (
    PRODUCT_MODULES,
    Booking,
    Guest,
    HotelRoomType,
    Location,
    Membership,
    Offering,
    PaymentTransaction,
    RecreationProgramme,
    Resource,
    ScheduledEvent,
    Tenant,
    TenantModule,
    TicketType,
)
from app.services.booking import (
    BookingError,
    cancel_booking,
    create_clinic_booking,
    create_event_booking,
    create_facility_booking,
    create_hotel_booking,
    create_restaurant_reservation,
    enrol_in_programme,
)
from app.ui.seo import seo_meta

MODULE_LABELS = {
    "restaurant": ("Restaurants", "Food ordering, dine-in pre-orders, and tables"),
    "hotel": ("Hotels", "Room-type inventory and overnight stays"),
    "clinic": ("Private clinics", "FastClinic-connected appointments"),
    "events": ("Events", "Concerts, ticket types, and capacity"),
    "recreation": (
        "Sport & recreation",
        "Aquatics, programmes, memberships, visits, and facilities",
    ),
}
BOOKING_VIEWS = {
    "restaurant": {
        "title": "Reserve a table",
        "lede": "Choose a time and party size. FastBooking allocates a suitable table without double-booking it.",
        "image": "/static/images/table-reservation.jpg",
        "credit": ("Adrien Olichon", "https://unsplash.com/photos/h2_8LFfjUUc"),
    },
    "hotel": {
        "title": "Find your stay",
        "lede": "Compare room types, choose your dates, and reserve live nightly inventory in one step.",
        "image": "/static/images/hotel-booking.jpg",
        "credit": ("Alex Muzenhardt", "https://unsplash.com/photos/4MQ0T4zBIys"),
    },
    "clinic": {
        "title": "Book an appointment",
        "lede": "Select a service and practitioner. Clinical records remain securely in FastClinic.",
        "image": "/static/images/clinic-booking.jpg",
        "credit": ("Vitaly Gariev", "https://unsplash.com/photos/7-l5EL7YHI4"),
    },
    "events": {
        "title": "Book an event",
        "lede": "See what is on, choose a ticket, and receive an immediate booking confirmation.",
        "image": "/static/images/event-booking.jpg",
        "credit": ("kofa boyah", "https://unsplash.com/photos/St-6SCwofGo"),
    },
    "recreation": {
        "title": "Book sport and recreation",
        "lede": "Reserve a court, room, lane, or programme with live capacity and conflict checks.",
        "image": "/static/images/aquatics-booking.jpg",
        "card_image": "/static/images/facility-booking.jpg",
        "credit": ("Yanping Ma", "https://unsplash.com/photos/QIZFFoGzuaI"),
    },
}
PARTNERS = (
    ("SAASPASS", "https://saaspass.com/", "https://saaspass.com/_next/static/assets/0176aeff921f6359fee88e796be31ace.png", "Full-stack identity and access management spanning MFA, SSO, passwordless access and integration APIs."),
    ("Sixty Four", "https://sixtyfour.ee/", "https://sixtyfour.ee/favicon.ico", "A senior Tallinn technology studio delivering software, AI consultancy, service design and public-sector programmes."),
    ("EDI Labs", "https://edilabs.tech/", "https://edilabs.tech/static/favicon.svg", "AI and data engineering for document intelligence, forecasting, geospatial systems and agentic workflows."),
    ("Predictive Labs", "https://predictivelabs.ai/", "https://predictivelabs.ai/static/favicon.svg", "Auditable AI systems for health, defence, public management, mobility and financial services."),
    ("Consistente", "https://consistente.tech/", "https://consistente.tech/static/favicon.svg", "Enterprise AI delivery across financial services, healthcare, the public sector and technology."),
    ("Manmouna Technologies", "https://manmouna.tech/", "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%230B1E14'/%3E%3Cpath d='M32 12 52 32 32 52 12 32Z' fill='%2334D399'/%3E%3Cpath d='M32 22 42 32 32 42 22 32Z' fill='%230B1E14'/%3E%3C/svg%3E", "Auditable-by-design AI systems for European public services across health, defence, public management and mobility."),
)
INTEGRATIONS = (
    (
        "FastCRM",
        "Pair booking and membership activity with contacts, tasks and relationship timelines.",
        "https://crm.fastsme.com",
    ),
    (
        "FastERP",
        "Hand settlement reconciliation, invoicing and general-ledger workflows to the finance system.",
        "https://erp.fastsme.com",
    ),
    (
        "FastInsights",
        "Take governed booking, utilisation, attendance and revenue data into operational dashboards.",
        "https://insights.fastsme.com",
    ),
    (
        "FastMail",
        "Extend service communications into a shared team inbox and coordinated customer follow-up.",
        "https://mail.fastsme.com",
    ),
    (
        "FastClinic",
        "Keep clinical records in the clinical system while FastBooking owns appointment allocation.",
        "https://clinic.fastsme.com",
    ),
    (
        "FastSSO",
        "Connect workforce identity and access without weakening FastBooking tenant boundaries.",
        "https://github.com/predictivelabsai/FastSSO",
    ),
)
INDUSTRIES = {
    "sport-recreation": {
        "name": "Sport & recreation",
        "eyebrow": "Councils, trusts and multi-facility operators",
        "summary": "Coordinate facilities, memberships, programmes, visits and revenue across community recreation services.",
        "image": "/static/images/facility-booking.jpg",
        "outcomes": (
            "Give residents one place to discover courts, rooms, programmes and memberships.",
            "Prevent clashes across stadiums, courts, rooms and shared equipment.",
            "Track bookings, attendance, casual visits, payments and refunds together.",
        ),
        "workflow": (
            ("Publish", "Configure bookable locations, resources, capacity, opening windows and prices."),
            ("Allocate", "Check resource conflicts before confirming a facility or programme place."),
            ("Serve", "Give front-desk teams current entitlement, arrival and booking context."),
            ("Review", "Monitor demand, utilisation, attendance, revenue and exceptions by facility."),
        ),
        "integration": "Use FastCRM for relationship follow-up, FastERP for finance hand-off and FastInsights for governed operational analysis.",
    },
    "aquatics-swim-schools": {
        "name": "Aquatics & swim schools",
        "eyebrow": "Pools, aquatic centres and learn-to-swim teams",
        "summary": "Run lessons, term enrolments, pool capacity and lane allocation without separating the customer journey from daily operations.",
        "image": "/static/images/aquatics-booking.jpg",
        "outcomes": (
            "Structure terms, sessions, levels, capacity and waitlists for learn-to-swim programmes.",
            "Allocate pools and lanes around lessons, clubs, casual swimming and maintenance windows.",
            "Record attendance and no-shows while retaining a clear enrolment and payment trail.",
        ),
        "workflow": (
            ("Plan", "Create programme offerings and reserve the required pool or lane capacity."),
            ("Enrol", "Let families choose a suitable session with live places and clear pricing."),
            ("Attend", "Record participation, no-shows and casual visits at the facility."),
            ("Improve", "Review fill rates, attendance patterns, income and under-used capacity."),
        ),
        "integration": "Send relationship follow-up to FastCRM and governed programme, attendance and revenue measures to FastInsights.",
    },
    "restaurants": {
        "name": "Restaurants",
        "eyebrow": "Dining rooms, venues and hospitality groups",
        "summary": "Turn live table capacity into a straightforward guest reservation journey, with optional ordering and payment context.",
        "image": "/static/images/table-reservation.jpg",
        "outcomes": (
            "Allocate a suitable table from party size and reservation time.",
            "Avoid overlapping reservations while keeping staff control of inventory.",
            "Connect booking, guest and payment status without forcing restaurant workflows into a calendar form.",
        ),
        "workflow": (
            ("Discover", "Present locations, service windows and availability on a responsive booking page."),
            ("Reserve", "Capture party size and contact details, then allocate a conflict-free table."),
            ("Serve", "Give the team a current reservation list and secure customer management link."),
            ("Follow up", "Pass broader guest relationships and team communications to FastCRM and FastMail."),
        ),
        "integration": "FastBooking owns reservation allocation; FastCRM can retain the wider guest relationship and FastERP can receive settlement data.",
    },
    "hotels": {
        "name": "Hotels & accommodation",
        "eyebrow": "Independent hotels, lodges and accommodation groups",
        "summary": "Sell room-type inventory by night with a customer journey designed for stays rather than hourly appointments.",
        "image": "/static/images/hotel-booking.jpg",
        "outcomes": (
            "Expose room types, nightly availability and stay pricing in one booking flow.",
            "Reserve inventory across every night in a stay and avoid overselling capacity.",
            "Keep confirmations, payments, refunds and cancellations tied to the booking record.",
        ),
        "workflow": (
            ("Search", "Let guests compare room types for arrival and departure dates."),
            ("Price", "Calculate the stay from nightly inventory and configured rates."),
            ("Confirm", "Hold the required inventory and issue a secure booking management link."),
            ("Reconcile", "Track payment state and hand accounting workflows to FastERP."),
        ),
        "integration": "Connect FastCRM for guest relationships, FastMail for shared communications and FastERP for finance workflows.",
    },
    "clinics": {
        "name": "Clinics & allied health",
        "eyebrow": "Private clinics and appointment-led services",
        "summary": "Offer a focused appointment journey while keeping clinical records inside FastClinic and operational booking data inside FastBooking.",
        "image": "/static/images/clinic-booking.jpg",
        "outcomes": (
            "Publish services, practitioners and appointment availability without exposing clinical data.",
            "Check resource and practitioner allocation before confirmation.",
            "Retain a strict boundary: booking references here, clinical records in FastClinic.",
        ),
        "workflow": (
            ("Choose", "Let patients select a service, practitioner and available appointment."),
            ("Allocate", "Confirm the time against the relevant booking resources."),
            ("Attend", "Use the booking reference to coordinate arrival and operational status."),
            ("Treat", "Continue clinical documentation and care workflows in FastClinic."),
        ),
        "integration": "FastClinic remains the clinical system of record; only allocation references cross the integration boundary.",
    },
    "events-venues": {
        "name": "Events & venues",
        "eyebrow": "Community events, performances and ticketed venues",
        "summary": "Publish scheduled events, sell capacity-controlled ticket types and keep confirmations and payment status together.",
        "image": "/static/images/event-booking.jpg",
        "outcomes": (
            "Create scheduled events with ticket types, prices and capacity limits.",
            "Give customers a direct event-specific booking and confirmation journey.",
            "See ticket sales, booking status, payments and refunds in the admin view.",
        ),
        "workflow": (
            ("Publish", "Configure the event, venue context, ticket types, price and capacity."),
            ("Book", "Let customers select tickets and create a capacity-checked reservation."),
            ("Confirm", "Issue the booking reference and retain payment status alongside it."),
            ("Analyse", "Take attendance, sales and utilisation measures into FastInsights."),
        ),
        "integration": "Use FastCRM and FastMail for audience relationships and communications, with FastERP and FastInsights downstream.",
    },
}
PUBLIC_NAV_LINKS = (
    ("Features", "/features"),
    ("Industries", "/industries"),
    ("Tour", "/tour"),
    ("Integrations", "/integrations"),
    ("Pricing", "/#pricing"),
    ("Partners", "/partners"),
    ("Compare", "/compare"),
    ("Developers", "/developers"),
)
CSS = """
:root{--accent:#0f766e;--accent-dark:#0a5b55;--tint:#f0fdfa;--ink:#12302d;--muted:#61726f;--line:#dce8e5;--soft:#f7faf9}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:var(--ink);font-family:Inter,system-ui,sans-serif}.nav-wrap{border-bottom:1px solid var(--line);position:relative;z-index:10;background:rgba(255,255,255,.96)}
.nav{height:72px;display:flex;align-items:center;justify-content:space-between;max-width:1180px;margin:auto;padding:0 24px}.nav-links{display:flex;align-items:center;gap:18px}.nav-links>a:not(.button){font-size:13px;font-weight:600;color:var(--muted);text-decoration:none}.nav-links>a:hover{color:var(--ink)}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;color:var(--ink);text-decoration:none}.mark{width:34px;height:34px;border-radius:11px;background:var(--accent);display:grid;place-items:center;color:#fff;box-shadow:0 7px 18px rgba(15,118,110,.2)}
.button{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:999px;padding:12px 20px;text-decoration:none;font-weight:700;font-size:14px;background:var(--accent);color:#fff;cursor:pointer;transition:.2s}.button:hover{background:var(--accent-dark);transform:translateY(-1px)}.outline{background:#fff;color:var(--ink);border:1px solid var(--line)}.outline:hover{background:var(--soft);color:var(--ink)}
.hero{max-width:1180px;margin:auto;padding:82px 24px 72px;display:grid;grid-template-columns:1.08fr .92fr;gap:66px;align-items:center}.kicker{color:var(--accent);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.16em}.hero h1{font-size:clamp(46px,6.2vw,74px);line-height:1.01;letter-spacing:-.058em;max-width:740px;margin:20px 0 24px}.lede{font-size:19px;line-height:1.65;color:var(--muted);max-width:690px;margin:0 0 30px}.hero-note{color:var(--muted);font-size:13px;margin:14px 0 0}
.ops{background:#fff;border:1px solid var(--line);border-radius:26px;box-shadow:0 28px 80px rgba(18,48,45,.12);overflow:hidden;transform:rotate(1deg)}.ops-head{padding:17px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}.ops-title{font-size:13px;font-weight:800}.live{font-size:11px;font-weight:800;color:var(--accent);background:var(--tint);border-radius:99px;padding:6px 9px}.ops-body{padding:14px}.ops-row{display:grid;grid-template-columns:44px 1fr auto;gap:12px;align-items:center;padding:13px 8px;border-bottom:1px solid #edf2f1}.ops-row:last-child{border:0}.ops-time{font-size:12px;color:var(--muted)}.ops-name{font-size:13px;font-weight:700}.ops-meta{display:block;font-size:11px;color:var(--muted);font-weight:500;margin-top:3px}.status{font-size:11px;font-weight:700;border-radius:99px;padding:6px 8px;background:var(--tint);color:var(--accent)}.status.warn{background:#fff7ed;color:#b45309}.ops-kpis{display:grid;grid-template-columns:repeat(3,1fr);background:var(--soft);border-top:1px solid var(--line)}.ops-kpi{padding:16px;border-right:1px solid var(--line)}.ops-kpi:last-child{border:0}.ops-kpi strong{display:block;font-size:20px}.ops-kpi span{font-size:10px;color:var(--muted)}
.proof{border-block:1px solid var(--line);background:var(--soft)}.proof-inner{max-width:1180px;margin:auto;padding:20px 24px;display:flex;justify-content:space-between;gap:24px;color:var(--muted);font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}.proof-inner span:before{content:'✓';color:var(--accent);margin-right:8px}
.demo-section{max-width:1180px;margin:auto;padding:92px 24px 18px}.demo-head{display:flex;align-items:end;justify-content:space-between;gap:50px;margin-bottom:34px}.demo-head h2{font-size:clamp(34px,4vw,50px);letter-spacing:-.045em;line-height:1.08;margin:14px 0 0;max-width:650px}.demo-head p{color:var(--muted);font-size:16px;line-height:1.65;max-width:440px;margin:0}.demo-frame{margin:0;border:1px solid var(--line);border-radius:24px;padding:10px;background:var(--soft);box-shadow:0 24px 70px rgba(18,48,45,.1);overflow:hidden}.demo-frame img{display:block;width:100%;height:auto;border-radius:16px}.demo-frame figcaption{padding:12px 8px 4px;color:var(--muted);font-size:12px}
.section{max-width:1180px;margin:auto;padding:92px 24px}.section>.button{margin-top:30px}.section-head{display:grid;grid-template-columns:.8fr 1.2fr;gap:70px;align-items:end;margin-bottom:38px}.section h2{font-size:clamp(34px,4vw,50px);letter-spacing:-.045em;line-height:1.08;margin:14px 0 0}.section-intro{font-size:17px;line-height:1.65;color:var(--muted);margin:0}.cap-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.cap-card{border:1px solid var(--line);border-radius:19px;padding:23px;background:#fff;min-height:224px}.cap-icon{display:grid;place-items:center;width:36px;height:36px;border-radius:11px;background:var(--tint);color:var(--accent);font-size:16px;font-weight:800}.cap-card h3{font-size:16px;line-height:1.3;margin:19px 0 9px}.cap-card p{font-size:13px;line-height:1.62;color:var(--muted);margin:0}
.journey-band{background:var(--ink);color:#fff}.journey{max-width:1180px;margin:auto;padding:84px 24px}.journey .kicker{color:#5eead4}.journey h2{font-size:clamp(34px,4vw,50px);letter-spacing:-.045em;max-width:720px;margin:14px 0 44px}.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.14);border-radius:20px;overflow:hidden}.step{background:var(--ink);padding:28px}.step b{color:#5eead4;font-size:11px;letter-spacing:.1em}.step h3{font-size:17px;margin:16px 0 8px}.step p{font-size:13px;line-height:1.55;color:#b9cfcb;margin:0}
.integrations{background:var(--tint);border-block:1px solid #cfe7e2}.integration-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.integration{background:#fff;border:1px solid #cfe7e2;border-radius:18px;padding:22px}.integration strong{display:block;font-size:15px;margin-bottom:9px}.integration p{font-size:13px;line-height:1.55;color:var(--muted);margin:0}.integration a{color:var(--accent);font-weight:700;text-decoration:none}
.industries{background:var(--soft);border-block:1px solid var(--line)}.industry-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.industry-detail>.industry-grid+.industry-grid{margin-top:16px}.industry-card{overflow:hidden;border:1px solid var(--line);border-radius:20px;background:#fff;color:var(--ink);text-decoration:none}.industry-card img{display:block;width:100%;height:172px;object-fit:cover}.industry-card-body{padding:22px}.industry-card h3{font-size:18px;margin:0 0 9px}.industry-card p{color:var(--muted);font-size:13px;line-height:1.6;margin:0 0 18px}.industry-card small{color:var(--accent);font-weight:750}.industry-detail{max-width:1180px;margin:auto;padding:28px 24px 92px}.industry-detail-hero{display:grid;grid-template-columns:1fr 1fr;gap:34px;align-items:center}.industry-detail-hero img{display:block;width:100%;height:390px;object-fit:cover;border-radius:24px}.industry-detail-copy h1{font-size:clamp(42px,5.5vw,66px);line-height:1.03;letter-spacing:-.055em;margin:18px 0}.industry-detail-copy p{color:var(--muted);font-size:18px;line-height:1.65}.outcome-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:52px 0}.outcome-card{border:1px solid var(--line);border-radius:18px;padding:22px;background:#fff}.outcome-card b{color:var(--accent);font-size:11px;letter-spacing:.1em}.outcome-card p{line-height:1.6;margin:12px 0 0}.workflow-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:20px;overflow:hidden}.workflow-card{padding:24px;background:var(--soft)}.workflow-card b{color:var(--accent);font-size:11px;letter-spacing:.1em}.workflow-card h2{font-size:17px;margin:14px 0 8px}.workflow-card p{font-size:13px;line-height:1.55;color:var(--muted);margin:0}.boundary{margin-top:42px;padding:26px;border:1px solid #cfe7e2;border-radius:20px;background:var(--tint)}.boundary h2{font-size:20px;margin:0 0 9px}.boundary p{color:var(--muted);line-height:1.6;margin:0}
.partners{scroll-margin-top:80px}.partner-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.partner-card{min-width:0;border:1px solid var(--line);border-radius:18px;padding:24px;color:var(--ink);text-decoration:none;background:#fff;transition:transform .18s,border-color .18s,box-shadow .18s}.partner-card:hover{transform:translateY(-3px);border-color:#8fc9be;box-shadow:0 14px 34px rgba(17,24,39,.08)}.partner-card-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.partner-card-head img{width:48px;height:48px;object-fit:contain}.partner-card-head span{color:var(--accent);font-size:9px;font-weight:800;letter-spacing:.08em;text-align:right;text-transform:uppercase}.partner-card h3{margin:20px 0 8px}.partner-card p{min-height:64px;color:var(--muted);font-size:13px;line-height:1.55}.partner-card small{color:var(--accent);font-weight:750}
.cta{max-width:1132px;margin:92px auto;padding:62px;border-radius:26px;background:var(--tint);border:1px solid #cfe7e2;text-align:center}.cta h2{font-size:clamp(34px,4vw,50px);letter-spacing:-.045em;margin:12px auto 18px;max-width:760px}.cta p{color:var(--muted);font-size:17px;line-height:1.6;max-width:700px;margin:0 auto 28px}
.shell{max-width:1180px;margin:44px auto;padding:0 24px}.head{display:flex;justify-content:space-between;align-items:center;gap:20px}.modules{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:28px}.module{border:1px solid var(--line);border-radius:18px;padding:22px}.module.enabled{border-color:var(--accent);background:var(--tint)}.notice{max-width:1180px;margin:16px auto 0;padding:12px 24px;color:#92400e}.footer{max-width:1180px;margin:auto;padding:38px 24px;color:var(--muted);display:flex;justify-content:space-between;font-size:13px;border-top:1px solid var(--line)}.footer a{color:var(--accent);text-decoration:none;font-weight:700}
.page-hero{max-width:950px;margin:auto;padding:82px 24px 44px;text-align:center}.page-hero h1{font-size:clamp(42px,6vw,68px);line-height:1.03;letter-spacing:-.055em;margin:18px 0}.page-hero p{max-width:720px;margin:auto;color:var(--muted);font-size:18px;line-height:1.65}.feature-groups{max-width:1180px;margin:auto;padding:28px 24px 92px;display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.feature-group{border:1px solid var(--line);border-radius:22px;padding:26px}.feature-group h2{font-size:21px;margin:0 0 8px}.feature-group>p{color:var(--muted);line-height:1.55}.check-list{list-style:none;padding:0;margin:20px 0 0}.check-list li{padding:10px 0;border-top:1px solid var(--line);font-size:14px}.check-list li:before{content:'✓';color:var(--accent);font-weight:800;margin-right:10px}.cmp-wrap{max-width:1180px;margin:auto;padding:20px 24px 92px}.cmp-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:22px}.cmp-table{width:100%;border-collapse:collapse;min-width:960px;background:#fff}.cmp-table caption{text-align:left;padding:18px;color:var(--muted);font-size:12px}.cmp-table th,.cmp-table td{text-align:left;vertical-align:top;padding:16px;border-top:1px solid var(--line);font-size:13px;line-height:1.5}.cmp-table th{background:var(--soft);font-size:11px;text-transform:uppercase;letter-spacing:.06em}.cmp-table tr.fastbooking{background:var(--tint)}.cmp-table a{color:var(--accent);font-weight:700}.cmp-note{font-size:12px;color:var(--muted);line-height:1.55}.dashboard{max-width:1240px;margin:auto;padding:32px 24px 70px}.dash-nav{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:30px}.dash-actions{display:flex;gap:14px;align-items:center}.dash-actions a{color:var(--muted);font-size:13px;font-weight:700;text-decoration:none}.role{background:var(--tint);color:var(--accent);border-radius:99px;padding:7px 10px;font-size:11px;font-weight:800;text-transform:uppercase}.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.kpi-card{border:1px solid var(--line);border-radius:18px;padding:20px;background:#fff}.kpi-card span{color:var(--muted);font-size:12px}.kpi-card strong{display:block;font-size:28px;margin-top:9px}.dash-grid{display:grid;grid-template-columns:1.45fr .85fr;gap:18px;margin-top:18px}.panel{border:1px solid var(--line);border-radius:20px;background:#fff;overflow:hidden}.panel-head{padding:20px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line)}.panel-head h2{font-size:17px;margin:0}.data-table{width:100%;border-collapse:collapse}.data-table th,.data-table td{text-align:left;padding:13px 18px;border-bottom:1px solid var(--line);font-size:12px}.data-table th{color:var(--muted);font-size:10px;text-transform:uppercase}.empty{padding:28px;color:var(--muted)}.config-grid{padding:14px;display:grid;gap:10px}.config-row{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:13px;border:1px solid var(--line);border-radius:14px}.config-row h3{font-size:13px;margin:0}.config-row p{font-size:11px;color:var(--muted);margin:4px 0 0}.booking-hero{height:310px;background-size:cover;background-position:center;position:relative;color:#fff}.booking-hero:after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,rgba(10,33,30,.83),rgba(10,33,30,.18))}.booking-hero-inner{position:relative;z-index:1;max-width:1180px;margin:auto;padding:70px 24px}.booking-hero h1{font-size:clamp(38px,5vw,62px);letter-spacing:-.05em;margin:12px 0}.booking-hero p{max-width:580px;line-height:1.55;color:#e3efed}.booking-layout{max-width:1180px;margin:-38px auto 70px;padding:0 24px;position:relative;z-index:2;display:grid;grid-template-columns:1.2fr .8fr;gap:18px}.booking-panel{background:#fff;border:1px solid var(--line);border-radius:22px;padding:25px;box-shadow:0 20px 55px rgba(18,48,45,.1)}.booking-panel h2{margin:0 0 8px}.options{display:grid;gap:10px;margin-top:20px}.option{border:1px solid var(--line);border-radius:14px;padding:15px}.option strong{display:block}.option span{font-size:12px;color:var(--muted)}.booking-form{display:grid;grid-template-columns:1fr 1fr;gap:13px}.booking-form label{font-size:11px;font-weight:800;color:var(--muted)}.booking-form input,.booking-form select,.booking-form textarea{width:100%;margin-top:6px;border:1px solid var(--line);border-radius:10px;padding:11px;font:inherit;background:#fff}.booking-form .wide{grid-column:1/-1}.photo-credit{font-size:10px;color:var(--muted);margin-top:14px}.photo-credit a{color:inherit}.success{background:var(--tint);border:1px solid #b7dfd7;border-radius:18px;padding:22px}
@media(max-width:900px){.hero,.industry-detail-hero{grid-template-columns:1fr;gap:46px}.cap-grid,.integration-grid,.partner-grid,.industry-grid,.outcome-grid{grid-template-columns:repeat(2,1fr)}.steps,.workflow-grid{grid-template-columns:repeat(2,1fr)}.section-head,.demo-head{display:grid;grid-template-columns:1fr;gap:20px}.proof-inner{flex-wrap:wrap}.nav-links>a:not(.button){display:none}}
@media(max-width:900px){.feature-groups,.dash-grid,.booking-layout{grid-template-columns:1fr}.kpi-grid{grid-template-columns:repeat(2,1fr)}.booking-layout{margin-top:-25px}}
@media(max-width:580px){.nav{padding:0 18px}.nav-links{gap:10px}.hero{padding:58px 20px 52px}.hero h1{font-size:44px}.section,.journey,.demo-section{padding:68px 20px}.cap-grid,.integration-grid,.partner-grid,.industry-grid,.outcome-grid,.workflow-grid,.steps,.modules,.feature-groups,.kpi-grid{grid-template-columns:1fr}.industry-detail-hero img{height:280px}.proof-inner{display:grid;grid-template-columns:1fr 1fr}.ops{transform:none}.ops-kpis{grid-template-columns:1fr}.ops-kpi{border-right:0;border-bottom:1px solid var(--line)}.demo-frame{border-radius:16px;padding:6px}.demo-frame img{border-radius:11px}.cta{margin:56px 20px;padding:45px 22px}.footer{flex-direction:column;gap:12px}.brand{font-size:14px}.button{padding:10px 15px}.booking-form{grid-template-columns:1fr}.booking-form .wide{grid-column:auto}.data-table{min-width:650px}.panel{overflow-x:auto}.dash-nav{align-items:flex-start}.dash-actions{flex-wrap:wrap;justify-content:flex-end}}
"""


def _head(
    title: str,
    *,
    seo_path: str | None = None,
    extra: tuple = (),
    description: str = (
        "Configurable bookings for sport, recreation, hospitality, clinics, and events."
    ),
):
    return Head(
        Title(title),
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(name="description", content=description),
        *(
            seo_meta(path=seo_path, title=title, description=description)
            if seo_path
            else ()
        ),
        Link(
            rel="icon",
            href=(
                "data:image/svg+xml,"
                "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
                "<rect width='32' height='32' rx='8' fill='%230f766e'/>"
                "<path d='M10 7h13v5h-7v3h6v5h-6v6h-6z' fill='white'/></svg>"
            ),
        ),
        Link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
        ),
        Style(CSS),
        *extra,
    )


def _industry_card(slug: str, industry: dict):
    return A(
        Img(src=industry["image"], alt="", loading="lazy"),
        Div(
            H3(industry["name"]),
            P(industry["summary"]),
            Small("Explore this industry →"),
            cls="industry-card-body",
        ),
        href=f"/industries/{slug}",
        cls="industry-card",
    )


def _partner_grid():
    return Div(
        *[
            A(
                Div(
                    Img(src=logo_url, alt=f"{name} logo", loading="lazy"),
                    Span("Integration Partner"),
                    cls="partner-card-head",
                ),
                H3(name),
                P(description),
                Small("Visit website ↗"),
                href=url,
                target="_blank",
                rel="noopener noreferrer",
                cls="partner-card",
            )
            for name, url, logo_url, description in PARTNERS
        ],
        cls="partner-grid",
    )



def pricing_section():
    return Section(
        Div(Div(Span("Pricing", cls="kicker"), H2("Simple pricing for every FastSME product.")), P("Every Fast* product uses the same two options: bring your own cloud for free, or host with us for €1 per month.", cls="section-intro"), cls="section-head"),
        Div(
            Article(Span("BYOC", cls="kicker"), H3("Bring Your Own Cloud"), P(Strong("Free")), P("Self-host on your own infrastructure or cloud. Full control of data and upgrades. No per-seat platform fee."), cls="card"),
            Article(Span("Hosted", cls="kicker"), H3("Host with us"), P(Strong("€1 / month")), P("We run the product for you on FastSME-managed infrastructure. €1 per product per month."), cls="card"),
            cls="card-grid",
        ),
        id="pricing", cls="section",
    )

def landing_page(message: str = ""):
    capabilities = (
        (
            "01",
            "Swimming lessons & programmes",
            "Schedule terms and sessions, manage capacity and waitlists, enrol customers, and record attendance.",
        ),
        (
            "02",
            "Aquatics & lane allocation",
            "Allocate pools, lanes and shared capacity with conflict checks across bookings and programmed activity.",
        ),
        (
            "03",
            "Memberships & access",
            "Offer gym and fitness plans, fixed-term passes and visit packs with entitlement-aware check-in.",
        ),
        (
            "04",
            "Casual visits",
            "Record front-desk and self-service arrivals, validate active access and keep a reliable visit history.",
        ),
        (
            "05",
            "Facility bookings",
            "Book stadiums, courts, rooms and other resources by time, capacity, location and price.",
        ),
        (
            "06",
            "Customer self-service",
            "Let customers discover availability, book, enrol, pay, receive reminders and manage cancellations online.",
        ),
        (
            "07",
            "Customer communications",
            "Maintain tenant-scoped customer profiles and consent, with durable confirmations, reminders and cancellation notices.",
        ),
        (
            "08",
            "Payments & reporting",
            "Use hosted online checkout or pay at facility, then report booking value, payment state, refunds and visits.",
        ),
    )
    capability_cards = [
        Article(
            Span(number, cls="cap-icon"),
            H3(title),
            P(description),
            cls="cap-card",
        )
        for number, title, description in capabilities
    ]
    return Html(
        _head(
            "FastBooking · Sport and recreation management",
            seo_path="/",
            description=(
                "Modern recreation management software for aquatic programmes, "
                "memberships, facility bookings, customer self-service, payments, "
                "attendance and reporting."
            ),
        ),
        Body(
            _public_nav(),
            P(message, cls="notice") if message else None,
            Main(
                Section(
                    Div(
                        Span("Sport & recreation operations", cls="kicker"),
                        H1("Every facility, programme and member. In one place."),
                        P(
                            "Run aquatic programmes, memberships, casual access and "
                            "bookable community spaces through one multi-facility "
                            "platform—backed by simple customer self-service.",
                            cls="lede",
                        ),
                        A("View the product tour", href="/tour", cls="button"),
                        P(
                            "Tenant-scoped by design · Open APIs · Hosted or self-managed",
                            cls="hero-note",
                        ),
                    ),
                    Div(
                        Div(
                            Span("Queenstown Events Centre · Today", cls="ops-title"),
                            Span("Live operations", cls="live"),
                            cls="ops-head",
                        ),
                        Div(
                            Div(
                                Span("06:30", cls="ops-time"),
                                Span(
                                    "Adult lane swimming",
                                    Span("Alpine Aqualand · Lanes 1–4", cls="ops-meta"),
                                    cls="ops-name",
                                ),
                                Span("4 lanes", cls="status"),
                                cls="ops-row",
                            ),
                            Div(
                                Span("09:00", cls="ops-time"),
                                Span(
                                    "Learn to Swim · Kea 2",
                                    Span("Teaching pool · Term 3", cls="ops-meta"),
                                    cls="ops-name",
                                ),
                                Span("7 / 8", cls="status warn"),
                                cls="ops-row",
                            ),
                            Div(
                                Span("17:30", cls="ops-time"),
                                Span(
                                    "Social basketball",
                                    Span("Stadium · Court 2", cls="ops-meta"),
                                    cls="ops-name",
                                ),
                                Span("Confirmed", cls="status"),
                                cls="ops-row",
                            ),
                            cls="ops-body",
                        ),
                        Div(
                            Div(Strong("286"), Span("visits today"), cls="ops-kpi"),
                            Div(Strong("94%"), Span("programme fill"), cls="ops-kpi"),
                            Div(Strong("12"), Span("spaces in use"), cls="ops-kpi"),
                            cls="ops-kpis",
                        ),
                        cls="ops",
                    ),
                    cls="hero",
                ),
                Div(
                    Div(
                        Span("Multi-facility operations"),
                        Span("Conflict-safe allocation"),
                        Span("Customer self-service"),
                        Span("Auditable revenue"),
                        cls="proof-inner",
                    ),
                    cls="proof",
                ),
                Section(
                    Div(
                        Div(
                            Span("Industries", cls="kicker"),
                            H2("Purpose-built journeys on one booking core."),
                        ),
                        P(
                            "Use the operating model that fits each service—from lanes "
                            "and courts to tables, rooms, appointments and ticketed events.",
                            cls="section-intro",
                        ),
                        cls="section-head",
                    ),
                    Div(
                        *[_industry_card(slug, industry) for slug, industry in INDUSTRIES.items()],
                        cls="industry-grid",
                    ),
                    cls="section industries",
                ),
                Section(
                    Div(
                        Div(
                            Span("Platform walkthrough", cls="kicker"),
                            H2("See the whole recreation service at a glance."),
                        ),
                        P(
                            "A quick tour from live facility operations through "
                            "programmes, memberships, customer journeys, reporting, "
                            "and the wider Fast* ecosystem."
                        ),
                        cls="demo-head",
                    ),
                    Figure(
                        Img(
                            src="/static/product-demo.gif",
                            alt=(
                                "Animated walkthrough of the FastBooking sport and "
                                "recreation landing page"
                            ),
                            width="800",
                            height="450",
                            loading="lazy",
                            decoding="async",
                        ),
                        Figcaption(
                            "FastBooking sport and recreation platform walkthrough"
                        ),
                        cls="demo-frame",
                    ),
                    cls="demo-section",
                    id="tour",
                ),
                Section(
                    Div(
                        Div(
                            Span("Complete recreation management", cls="kicker"),
                            H2("One operational picture, from first enquiry to every visit."),
                        ),
                        P(
                            "FastBooking brings the daily work of aquatic, fitness and "
                            "community facilities together without forcing every service "
                            "into the same shape.",
                            cls="section-intro",
                        ),
                        cls="section-head",
                    ),
                    Div(*capability_cards, cls="cap-grid"),
                    cls="section",
                    id="capabilities",
                ),
                Div(
                    Section(
                        Span("Connected customer journey", cls="kicker"),
                        H2("Easy for residents. Clear for the team behind the counter."),
                        Div(
                            Div(
                                B("01 · DISCOVER"),
                                H3("Find the right option"),
                                P("Browse programmes, membership plans and available facilities by location."),
                                cls="step",
                            ),
                            Div(
                                B("02 · BOOK"),
                                H3("Reserve with confidence"),
                                P("Capacity and resource checks happen before a place or space is confirmed."),
                                cls="step",
                            ),
                            Div(
                                B("03 · PARTICIPATE"),
                                H3("Arrive and take part"),
                                P("Check in casual visitors and members, and track programme attendance."),
                                cls="step",
                            ),
                            Div(
                                B("04 · IMPROVE"),
                                H3("Understand demand"),
                                P("Review utilisation, income, payment status and visits across facilities."),
                                cls="step",
                            ),
                            cls="steps",
                        ),
                        cls="journey",
                    ),
                    cls="journey-band",
                ),
                Section(
                    Div(
                        Div(
                            Span("Fast* ecosystem", cls="kicker"),
                            H2("Purpose-built operations, connected to the wider customer picture."),
                        ),
                        P(
                            "FastBooking remains the source for availability, enrolment "
                            "and access. Open APIs provide clear boundaries to specialist "
                            "sister products when broader workflows are needed.",
                            cls="section-intro",
                        ),
                        cls="section-head",
                    ),
                    Div(
                        *[
                            Article(
                                Strong(A(name, href=url)),
                                P(description),
                                cls="integration",
                            )
                            for name, description, url in INTEGRATIONS
                        ],
                        cls="integration-grid",
                    ),
                    A("Explore integration boundaries", href="/integrations", cls="button"),
                    cls="section",
                    id="integrations",
                ),
                pricing_section(),
                    Section(
                    Div(Div(Span("Partners", cls="kicker"), H2("Connect with trusted integration specialists.")), P("Identity, software delivery, data engineering and applied-AI expertise for FastSME implementations.", cls="section-intro"), cls="section-head"),
                    _partner_grid(),
                    A("Meet our integration partners", href="/partners", cls="button"),
                    cls="section partners",
                    id="partners",
                ),
                Section(
                    Span("Ready for a better recreation experience?", cls="kicker"),
                    H2("Bring every booking and visit into focus."),
                    P(
                        "Start with one facility or configure a multi-site recreation "
                        "service with only the modules your team needs."
                    ),
                    A("Explore every feature", href="/features", cls="button"),
                    cls="cta",
                ),
            ),
            Footer(
                Span("FastBooking is part of the open-source FastSME suite."),
                A("Explore FastSME", href="https://fastsme.com/products"),
                cls="footer",
            ),
        ),
    )


def _public_nav():
    return Div(
        Nav(
            A(Span("F", cls="mark"), "FastBooking", href="/", cls="brand"),
            Div(
                *[A(label, href=href) for label, href in PUBLIC_NAV_LINKS],
                A("Sign In", href="/auth/google", cls="button outline"),
                cls="nav-links",
            ),
            cls="nav",
        ),
        cls="nav-wrap",
    )


def _public_footer():
    return Footer(
        Span("FastBooking is part of the open-source FastSME suite."),
        A("View source", href="https://github.com/predictivelabsai/FastBooking"),
        cls="footer",
    )


def industries_page():
    return Html(
        _head(
            "Industries · FastBooking",
            seo_path="/industries",
            description=(
                "See how FastBooking supports sport and recreation, aquatics, "
                "restaurants, hotels, clinics, events and venues."
            ),
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Span("Industry solutions", cls="kicker"),
                    H1("A booking journey shaped around the service."),
                    P(
                        "FastBooking shares customer, availability, payment and "
                        "reporting foundations while preserving the workflows that "
                        "make each industry different."
                    ),
                    cls="page-hero",
                ),
                Section(
                    *[
                        Div(
                            *[
                                _industry_card(slug, industry)
                                for slug, industry in list(INDUSTRIES.items())[index : index + 3]
                            ],
                            cls="industry-grid",
                        )
                        for index in range(0, len(INDUSTRIES), 3)
                    ],
                    cls="industry-detail",
                ),
                Section(
                    Span("Shared foundation", cls="kicker"),
                    H2("One operating picture across every service."),
                    P(
                        "Tenant-scoped data, role-based administration, secure "
                        "customer management links and provider-neutral payment "
                        "records stay consistent across all booking journeys."
                    ),
                    A("Explore every feature", href="/features", cls="button"),
                    cls="cta",
                ),
            ),
            _public_footer(),
        ),
    )


def industry_page(slug: str):
    industry = INDUSTRIES.get(slug)
    if industry is None:
        raise HTTPException(status_code=404, detail="Industry not found")
    return Html(
        _head(
            f"{industry['name']} booking software · FastBooking",
            seo_path=f"/industries/{slug}",
            description=industry["summary"],
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Div(
                        Span(industry["eyebrow"], cls="kicker"),
                        H1(industry["name"]),
                        P(industry["summary"]),
                        A("See platform features", href="/features", cls="button"),
                        cls="industry-detail-copy",
                    ),
                    Img(src=industry["image"], alt=f"{industry['name']} booking"),
                    cls="industry-detail-hero",
                ),
                Div(
                    *[
                        Article(
                            B(f"0{index}"),
                            P(outcome),
                            cls="outcome-card",
                        )
                        for index, outcome in enumerate(industry["outcomes"], 1)
                    ],
                    cls="outcome-grid",
                ),
                Div(
                    *[
                        Article(
                            B(f"0{index}"),
                            H2(title),
                            P(description),
                            cls="workflow-card",
                        )
                        for index, (title, description) in enumerate(
                            industry["workflow"], 1
                        )
                    ],
                    cls="workflow-grid",
                ),
                Aside(
                    H2("Clear product boundaries"),
                    P(industry["integration"]),
                    cls="boundary",
                ),
                cls="industry-detail",
            ),
            _public_footer(),
        ),
    )


def tour_page():
    scenes = (
        ("Live operations", "See bookings, programmes, visits and utilisation in context."),
        ("Capability map", "Move from aquatics and memberships through payments and reporting."),
        ("Industry journeys", "Give customers a view designed for the service they are booking."),
        ("Admin control", "Review bookings and payments while reserving product configuration for admins."),
    )
    return Html(
        _head(
            "Product tour · FastBooking",
            seo_path="/tour",
            description=(
                "Watch the FastBooking product tour covering recreation operations, "
                "customer booking journeys, payments and admin controls."
            ),
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Span("Product tour", cls="kicker"),
                    H1("See the booking operation as one connected service."),
                    P(
                        "The walkthrough moves from the public product story into "
                        "customer journeys and the operational admin view."
                    ),
                    cls="page-hero",
                ),
                Section(
                    Figure(
                        Img(
                            src="/static/product-demo.gif",
                            alt="Animated FastBooking product walkthrough",
                            width="800",
                            height="450",
                            decoding="async",
                        ),
                        Figcaption("FastBooking platform walkthrough"),
                        cls="demo-frame",
                    ),
                    cls="demo-section",
                ),
                Div(
                    *[
                        Article(
                            B(f"0{index}"),
                            H2(title),
                            P(description),
                            cls="workflow-card",
                        )
                        for index, (title, description) in enumerate(scenes, 1)
                    ],
                    cls="workflow-grid industry-detail",
                ),
            ),
            _public_footer(),
        ),
    )


def integrations_page():
    return Html(
        _head(
            "Integrations · FastBooking",
            seo_path="/integrations",
            description=(
                "Understand FastBooking integrations with FastCRM, FastERP, "
                "FastInsights, FastMail, FastClinic and FastSSO."
            ),
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Span("Fast* ecosystem", cls="kicker"),
                    H1("Connect booking operations without blurring ownership."),
                    P(
                        "FastBooking remains the source for availability, allocation, "
                        "enrolment and booking payment status. Sister products take "
                        "responsibility for the specialist records they understand best."
                    ),
                    cls="page-hero",
                ),
                Section(
                    Div(
                        *[
                            Article(
                                Strong(A(name, href=url)),
                                P(description),
                                cls="integration",
                            )
                            for name, description, url in INTEGRATIONS
                        ],
                        cls="industry-grid",
                    ),
                    Aside(
                        H2("The booking boundary"),
                        P(
                            "Tenant-scoped APIs expose only the data needed by each "
                            "integration. Clinical records stay in FastClinic, broader "
                            "relationships stay in FastCRM, accounting stays in FastERP, "
                            "and governed analytics stay in FastInsights."
                        ),
                        cls="boundary",
                    ),
                    cls="industry-detail",
                ),
            ),
            _public_footer(),
        ),
    )


def partners_page():
    return Html(
        _head(
            "Integration partners · FastBooking",
            seo_path="/partners",
            description=(
                "Meet FastBooking integration partners for identity, software "
                "delivery, data engineering and applied AI."
            ),
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Span("Integration partners", cls="kicker"),
                    H1("Specialists who help FastBooking connect and scale."),
                    P(
                        "Our partners bring identity, software delivery, data "
                        "engineering and applied-AI experience to FastSME implementations."
                    ),
                    cls="page-hero",
                ),
                Section(
                    _partner_grid(),
                    P(
                        "Partner descriptions are based on each organisation's public "
                        "profile. Follow the links for current services and capabilities.",
                        cls="cmp-note",
                    ),
                    cls="industry-detail partners",
                ),
            ),
            _public_footer(),
        ),
    )


def features_page():
    groups = (
        (
            "Aquatics and programmes",
            "Plan the full participant journey, not only the final booking.",
            (
                "Swimming lessons, terms, sessions, capacity, and waitlists",
                "Pool and lane allocations with conflict-safe resource checks",
                "Programme enrolment, attendance, no-shows, and visit history",
                "Flexible facilities, courts, rooms, and equipment inventory",
            ),
        ),
        (
            "Memberships and access",
            "Keep entitlements and arrivals visible to the people serving customers.",
            (
                "Gym, fitness, fixed-term, and multi-visit membership plans",
                "Casual access, front-desk check-in, and attendance records",
                "Membership validity and remaining-visit validation",
                "Multi-location services with tenant-scoped customer records",
            ),
        ),
        (
            "Bookings for every service",
            "Use a purpose-built journey while retaining one operating model.",
            (
                "Table reservations with party-size table allocation",
                "Hotel room types, nightly inventory, and stay pricing",
                "Event tickets, capacity, and customer confirmations",
                "FastClinic-connected appointments without storing clinical data",
            ),
        ),
        (
            "Payments and reporting",
            "Reconcile what was booked, paid, refunded, and attended.",
            (
                "Hosted online checkout and recorded on-site payments",
                "Provider-neutral payment ledger and refund visibility",
                "Booking value, payment state, attendance, and utilisation reporting",
                "FastERP and FastInsights hand-offs through tenant-scoped APIs",
            ),
        ),
        (
            "Customer self-service",
            "Give customers clear choices without exposing operational complexity.",
            (
                "Responsive discovery and booking views for each service type",
                "Secure hashed management links for cancellations",
                "Booking confirmations, reminders, and cancellation notices",
                "FastCRM referral for relationship timelines and follow-up",
            ),
        ),
        (
            "Administration and control",
            "Give the team a live view while keeping configuration privileged.",
            (
                "Admin dashboard for bookings, revenue, payments, and refunds",
                "Admin-only product-module configuration in UI and API",
                "Staff and viewer access without configuration permission",
                "Tenant isolation across operational and customer-owned data",
            ),
        ),
    )
    return Html(
        _head(
            "FastBooking Features · Recreation management software",
            seo_path="/features",
            description=(
                "Explore FastBooking capabilities for aquatics, programmes, "
                "memberships, facilities, customer self-service, payments, and reporting."
            ),
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Span("Complete capability map", cls="kicker"),
                    H1("One booking platform. Every kind of visit."),
                    P(
                        "FastBooking combines purpose-built customer journeys with a "
                        "shared, tenant-scoped operating model for teams running complex services."
                    ),
                    cls="page-hero",
                ),
                Div(
                    *[
                        Article(
                            H2(title),
                            P(description),
                            Ul(*[Li(item) for item in items], cls="check-list"),
                            cls="feature-group",
                        )
                        for title, description, items in groups
                    ],
                    cls="feature-groups",
                ),
                Section(
                    Span("See it in motion", cls="kicker"),
                    H2("A quick tour of modern recreation operations."),
                    P("Open the dedicated walkthrough and see the product in motion."),
                    A("Watch the demo", href="/tour", cls="button"),
                    cls="cta",
                ),
            ),
            _public_footer(),
        ),
    )


COMPARISONS = (
    {
        "name": "FastBooking",
        "fit": "Configurable multi-service and recreation operations",
        "scope": "Aquatics, programmes, memberships, facilities, visits, hospitality, clinic, and events",
        "self_service": "Responsive module-specific booking and management journeys",
        "finance": "Payment ledger, refunds, attendance, and financial reporting",
        "model": "MIT open source; hosted or self-managed",
        "buying": "Source available; implementation and hosting scoped separately",
        "source": "https://github.com/predictivelabsai/FastBooking",
    },
    {
        "name": "nextRec (Xplor Recreation)",
        "fit": "Parks, recreation, and multi-site community organisations",
        "scope": "Memberships, programmes, facilities, payments, CRM, access, and reporting",
        "self_service": "Online portal, embedded registration, mobile app, and kiosks",
        "finance": "POS, payments, analytics, and reporting",
        "model": "Proprietary cloud platform",
        "buying": "Request a demonstration",
        "source": "https://www.nextrec.com/",
    },
    {
        "name": "PerfectMind (now nextRec)",
        "fit": "The earlier PerfectMind brand of the current nextRec platform",
        "scope": "Facilities, activities, memberships, POS, inventory, and staff",
        "self_service": "Responsive public booking and registration",
        "finance": "POS plus financial, attendance, utilisation, and forecasting reports",
        "model": "Proprietary cloud platform",
        "buying": "Request a demonstration",
        "source": "https://www.nextrec.com/perfectmind-software",
    },
    {
        "name": "ACTIVE Network",
        "fit": "Community recreation, membership, and registration",
        "scope": "Membership, activity registration, facilities, child care, and communications",
        "self_service": "Online registrations, recurring payments, and account access",
        "finance": "Payments and operational administration",
        "model": "Proprietary hosted platform",
        "buying": "Request a demonstration",
        "source": "https://www.activenetwork.com/solutions/active-net",
    },
    {
        "name": "Jonas Leisure",
        "fit": "Australian and New Zealand leisure technology partnerships",
        "scope": "Product ecosystem for memberships, bookings, access, retention, and sales",
        "self_service": "Delivered through products including Envibe",
        "finance": "Payments and reporting across its leisure ecosystem",
        "model": "Proprietary regional product ecosystem",
        "buying": "Contact vendor",
        "source": "https://jonasleisure.com.au/products-overview",
    },
    {
        "name": "Legend",
        "fit": "Large leisure operators and multi-site sports organisations",
        "scope": "Memberships, courses, classes, events, rentals, access, and sales",
        "self_service": "Online joining, booking, parent portal, and mobile services",
        "finance": "Embedded payments, EPOS, invoicing, and business intelligence",
        "model": "Proprietary cloud platform",
        "buying": "Request a demonstration",
        "source": "https://www.legendware.co.uk/solutions/",
    },
    {
        "name": "Envibe",
        "fit": "Leisure and aquatic venues in Australia and New Zealand",
        "scope": "Memberships, swim school, programmes, bookings, POS, and access",
        "self_service": "Customer portal, online enrolment and bookings, and kiosks",
        "finance": "Payments, POS, and cross-module reporting",
        "model": "Proprietary Jonas Leisure platform",
        "buying": "Contact vendor",
        "source": "https://jonasleisure.com.au/products/envibe",
    },
)


def comparison_page():
    faq = (
        (
            "Is FastBooking open source?",
            "Yes. FastBooking publishes its source under the MIT licence and can be hosted or self-managed.",
        ),
        (
            "Does open source mean implementation is free?",
            "No. The software licence and source are distinct from infrastructure, migration, implementation, support, and payment-provider costs.",
        ),
        (
            "Why are vendor prices not shown?",
            "The compared vendors direct buyers to demonstrations or sales conversations on the cited product pages, so the matrix does not invent a price.",
        ),
    )
    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
            for question, answer in faq
        ],
    }
    rows = [
        Tr(
            Td(A(item["name"], href=item["source"])),
            Td(item["fit"]),
            Td(item["scope"]),
            Td(item["self_service"]),
            Td(item["finance"]),
            Td(item["model"]),
            Td(item["buying"]),
            cls="fastbooking" if item["name"] == "FastBooking" else "",
        )
        for item in COMPARISONS
    ]
    return Html(
        _head(
            "FastBooking comparison · Recreation management software",
            seo_path="/compare",
            description=(
                "Source-linked comparison of FastBooking with leading recreation "
                "and leisure management platforms."
            ),
            extra=(Script(
                NotStr(json.dumps(faq_schema, separators=(",", ":"))),
                type="application/ld+json",
            ),),
        ),
        Body(
            _public_nav(),
            Main(
                Section(
                    Span("How we compare", cls="kicker"),
                    H1("A clear view of the recreation software landscape."),
                    P(
                        "A source-linked comparison across operational scope, customer "
                        "self-service, finance, delivery model, and buying path."
                    ),
                    cls="page-hero",
                ),
                Section(
                    Div(
                        Table(
                            Caption(
                                "Public product information observed 9 August 2026. "
                                "Implementation, infrastructure, support, and payment costs may be separate."
                            ),
                            Thead(
                                Tr(
                                    Th("Platform"),
                                    Th("Best fit"),
                                    Th("Operational scope"),
                                    Th("Customer self-service"),
                                    Th("Payments & reporting"),
                                    Th("Delivery model"),
                                    Th("Buying path"),
                                )
                            ),
                            Tbody(*rows),
                            cls="cmp-table",
                        ),
                        cls="cmp-scroll",
                    ),
                    P(
                        "Claims are intentionally limited to the official vendor pages linked in each row. "
                        "PerfectMind and Xplor Recreation now share the nextRec product lineage. "
                        "Contact vendors for procurement-specific pricing, hosting, security, and service terms.",
                        cls="cmp-note",
                    ),
                    cls="cmp-wrap",
                ),
                Section(
                    H2("Questions people ask"),
                    *[Article(H3(question), P(answer)) for question, answer in faq],
                    cls="feature-groups",
                ),
            ),
            _public_footer(),
        ),
    )


async def _sign_in(identity: dict[str, str]) -> tuple[int, str | None, str | None]:
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == identity["email"]))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                email=identity["email"],
                username=identity["name"],
                role="user",
                is_active=True,
            )
            db.add(user)
            await db.flush()
        result = await db.execute(
            select(Membership, Tenant)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(Membership.user_id == user.id, Tenant.status == "active")
            .order_by(Membership.id)
        )
        existing = result.first()
        if existing:
            membership, tenant = existing
            await db.commit()
            return user.id, tenant.slug, membership.role
        await db.commit()
        return user.id, None, None


async def _session_access(session, db):
    user_id = session.get("user_id")
    tenant_slug = session.get("tenant_slug")
    if not isinstance(user_id, int) or not isinstance(tenant_slug, str):
        return None
    return (
        await db.execute(
            select(Tenant, Membership, User)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Tenant.slug == tenant_slug,
                Tenant.status == "active",
                Membership.user_id == user_id,
                User.is_active.is_(True),
            )
        )
    ).first()


def register_routes(app):
    @app.get("/features")
    async def features():
        return features_page()

    @app.get("/compare")
    async def compare():
        return comparison_page()

    @app.get("/industries")
    async def industries():
        return industries_page()

    @app.get("/industries/{industry_slug}")
    async def industry(industry_slug: str):
        return industry_page(industry_slug)

    @app.get("/tour")
    async def tour():
        return tour_page()

    @app.get("/integrations")
    async def integrations():
        return integrations_page()

    @app.get("/partners")
    async def partners():
        return partners_page()

    @app.get("/developers")
    async def developers():
        return Html(
            _head(
                "FastBooking API · Developers",
                seo_path="/developers",
                description=(
                    "Build tenant-scoped recreation, restaurant, hotel, clinic, and event "
                    "booking integrations with the FastBooking API."
                ),
            ),
            Body(
                _public_nav(),
                Main(
                    Span("Developers", cls="kicker"),
                    H1("Build on tenant-scoped booking APIs."),
                    P(
                        "Configure product modules, read public tenant catalogues, "
                        "and create conflict-checked facility bookings, programme "
                        "enrolments, memberships, and commerce journeys."
                    ),
                    Ul(
                        Li(Code("GET /api/v1/public/{tenant}/catalogue")),
                        Li(Code("POST /api/v1/public/{tenant}/bookings/restaurant")),
                        Li(Code("POST /api/v1/public/{tenant}/bookings/hotel")),
                        Li(Code("POST /api/v1/public/{tenant}/bookings/clinic")),
                        Li(Code("POST /api/v1/public/{tenant}/bookings/events")),
                        Li(
                            Code(
                                "POST /api/v1/public/{tenant}/bookings/"
                                "recreation/facilities"
                            )
                        ),
                        Li(
                            Code(
                                "POST /api/v1/public/{tenant}/bookings/"
                                "recreation/programmes"
                            )
                        ),
                        Li(Code("POST /api/v1/public/{tenant}/memberships")),
                    ),
                    A("Open interactive API docs", href="/api/docs", cls="button"),
                    P(A("Download OpenAPI JSON", href="/swagger.json")),
                    cls="shell",
                ),
                _public_footer(),
            ),
        )

    @app.get("/swagger.json")
    async def swagger():
        from app.api.main import create_api_app

        return JSONResponse(create_api_app().openapi())

    @app.get("/")
    async def landing(request, session):
        if session.get("user_id") and session.get("tenant_slug"):
            return RedirectResponse("/app", status_code=303)
        if session.get("user_id"):
            return RedirectResponse("/access-pending", status_code=303)
        messages = {
            "unconfigured": "Google sign-in is not configured for this deployment.",
            "failed": "Google sign-in failed. Please try again.",
            "unauthorised": "That Google account is not authorised.",
        }
        return landing_page(messages.get(request.query_params.get("auth", ""), ""))

    @app.get("/auth/google")
    async def google_start(request, session):
        if not google.enabled():
            return RedirectResponse("/?auth=unconfigured", status_code=303)
        state = google.new_state()
        session["google_oauth_state"] = state
        return RedirectResponse(google.authorize_url(request, state), status_code=303)

    @app.get("/auth/google/callback")
    async def google_callback(
        request, session, code: str = "", state: str = "", error: str = ""
    ):
        expected = session.pop("google_oauth_state", None)
        if error or not code or not secrets.compare_digest(state, expected or ""):
            return RedirectResponse("/?auth=failed", status_code=303)
        identity = await google.exchange(request, code)
        if not identity:
            return RedirectResponse("/?auth=unauthorised", status_code=303)
        user_id, tenant_slug, role = await _sign_in(identity)
        session["user_id"] = user_id
        if tenant_slug:
            session["tenant_slug"], session["role"] = tenant_slug, role
            return RedirectResponse("/app", status_code=303)
        session.pop("tenant_slug", None)
        session.pop("role", None)
        return RedirectResponse("/access-pending", status_code=303)

    @app.get("/access-pending")
    async def access_pending(session):
        if not session.get("user_id"):
            return RedirectResponse("/", status_code=303)
        if session.get("tenant_slug"):
            return RedirectResponse("/app", status_code=303)
        return Html(
            _head("Access pending · FastBooking"),
            Body(
                _public_nav(),
                Main(
                    Section(
                        Span("Account created", cls="kicker"),
                        H1("Your account is waiting for workspace access."),
                        P(
                            "FastBooking does not create automatic workspaces. "
                            "Ask your organisation administrator to invite this Google account."
                        ),
                        A("Sign out", href="/logout", cls="button outline"),
                        cls="page-hero",
                    )
                ),
                _public_footer(),
            ),
        )

    @app.get("/logout")
    async def logout(session):
        session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/app")
    async def workspace(session):
        async with async_session_factory() as db:
            access = await _session_access(session, db)
            if not access:
                return RedirectResponse("/access-pending", status_code=303)
            tenant, membership, _user = access
            modules = list(
                (
                await db.execute(
                    select(TenantModule)
                    .where(TenantModule.tenant_id == tenant.id)
                    .order_by(TenantModule.module)
                )
                ).scalars()
            )
            booking_count = await db.scalar(
                select(func.count(Booking.id)).where(Booking.tenant_id == tenant.id)
            ) or 0
            upcoming_count = await db.scalar(
                select(func.count(Booking.id)).where(
                    Booking.tenant_id == tenant.id,
                    Booking.starts_at >= datetime.datetime.now(datetime.UTC),
                    Booking.status.in_(("pending", "confirmed")),
                )
            ) or 0
            paid_total = await db.scalar(
                select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                    PaymentTransaction.tenant_id == tenant.id,
                    PaymentTransaction.status.in_(("paid", "refunded")),
                )
            ) or Decimal("0")
            refunded_total = await db.scalar(
                select(
                    func.coalesce(func.sum(PaymentTransaction.refunded_amount), 0)
                ).where(PaymentTransaction.tenant_id == tenant.id)
            ) or Decimal("0")
            booking_rows = (
                await db.execute(
                    select(Booking, Guest, Location)
                    .join(Guest, Guest.id == Booking.guest_id)
                    .join(Location, Location.id == Booking.location_id)
                    .where(Booking.tenant_id == tenant.id)
                    .order_by(Booking.created_at.desc())
                    .limit(10)
                )
            ).all()
            payment_rows = (
                await db.execute(
                    select(PaymentTransaction)
                    .where(PaymentTransaction.tenant_id == tenant.id)
                    .order_by(PaymentTransaction.occurred_at.desc())
                    .limit(8)
                )
            ).scalars().all()

        booking_table = (
            Table(
                Thead(Tr(Th("Reference"), Th("Customer"), Th("Service"), Th("When"), Th("Value"), Th("Status"))),
                Tbody(
                    *[
                        Tr(
                            Td(booking.public_reference),
                            Td(guest.name),
                            Td(f"{booking.module.title()} · {location.name}"),
                            Td(booking.starts_at.strftime("%d %b · %H:%M")),
                            Td(f"{tenant.currency} {booking.total:,.2f}"),
                            Td(Span(booking.status.title(), cls="status")),
                        )
                        for booking, guest, location in booking_rows
                    ]
                ),
                cls="data-table",
            )
            if booking_rows
            else P("No bookings have been created yet.", cls="empty")
        )
        payment_table = (
            Table(
                Thead(Tr(Th("Method"), Th("Amount"), Th("Refund"), Th("Status"))),
                Tbody(
                    *[
                        Tr(
                            Td(payment.payment_method.replace("_", " ").title()),
                            Td(f"{payment.currency} {payment.amount:,.2f}"),
                            Td(f"{payment.currency} {payment.refunded_amount:,.2f}"),
                            Td(Span(payment.status.title(), cls="status")),
                        )
                        for payment in payment_rows
                    ]
                ),
                cls="data-table",
            )
            if payment_rows
            else P("No payments have been recorded yet.", cls="empty")
        )
        config = Div(
            *[
                Div(
                    Div(
                        H3(MODULE_LABELS[item.module][0]),
                        P("Enabled" if item.enabled else "Not enabled"),
                    ),
                    Form(
                        Button(
                            "Disable" if item.enabled else "Enable",
                            cls="button outline",
                            type="submit",
                        ),
                        method="post",
                        action=f"/app/modules/{item.module}/toggle",
                    ),
                    cls="config-row",
                )
                for item in modules
            ],
            cls="config-grid",
        )
        return Html(
            _head(f"{tenant.name} dashboard · FastBooking"),
            Body(
                Main(
                    Div(
                        Div(
                            A(Span("F", cls="mark"), "FastBooking", href="/app", cls="brand"),
                            H1(tenant.name),
                        ),
                        Div(
                            Span(membership.role, cls="role"),
                            A("Customer site", href=f"/book/{tenant.slug}"),
                            A("Sign out", href="/logout"),
                            cls="dash-actions",
                        ),
                        cls="dash-nav",
                    ),
                    Div(
                        Article(Span("All bookings"), Strong(str(booking_count)), cls="kpi-card"),
                        Article(Span("Upcoming"), Strong(str(upcoming_count)), cls="kpi-card"),
                        Article(Span("Payments"), Strong(f"{tenant.currency} {paid_total:,.0f}"), cls="kpi-card"),
                        Article(Span("Refunded"), Strong(f"{tenant.currency} {refunded_total:,.0f}"), cls="kpi-card"),
                        cls="kpi-grid",
                    ),
                    Div(
                        Section(
                            Div(H2("Recent bookings"), Span("Latest 10"), cls="panel-head"),
                            booking_table,
                            cls="panel",
                        ),
                        Section(
                            Div(H2("Payments"), Span("Ledger"), cls="panel-head"),
                            payment_table,
                            cls="panel",
                        ),
                        cls="dash-grid",
                    ),
                    Section(
                        Div(
                            H2("Product configuration"),
                            Span("Admin only" if membership.role == "admin" else "Read only"),
                            cls="panel-head",
                        ),
                        config
                        if can_configure_products(membership.role)
                        else P("Only an administrator can change enabled products.", cls="empty"),
                        cls="panel",
                        style="margin-top:18px",
                    ),
                    cls="dashboard",
                )
            ),
        )

    @app.get("/admin")
    async def admin_redirect():
        return RedirectResponse("/app", status_code=303)

    @app.post("/app/modules/{module}/toggle")
    async def toggle_module(module: str, session):
        if module not in PRODUCT_MODULES or not session.get("user_id"):
            return RedirectResponse("/", status_code=303)
        async with async_session_factory() as db:
            configured = (
                await db.execute(
                    select(TenantModule)
                    .join(Tenant, Tenant.id == TenantModule.tenant_id)
                    .join(Membership, Membership.tenant_id == Tenant.id)
                    .where(
                        Tenant.slug == session.get("tenant_slug"),
                        Membership.user_id == session["user_id"],
                        Membership.role == ADMIN_ROLE,
                        TenantModule.module == module,
                    )
                )
            ).scalar_one_or_none()
            if configured:
                configured.enabled = not configured.enabled
                await db.commit()
        return RedirectResponse("/app", status_code=303)

    @app.get("/book/{tenant_slug}")
    async def public_tenant(tenant_slug: str):
        async with async_session_factory() as db:
            tenant = (
                await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            ).scalar_one_or_none()
            if not tenant:
                return landing_page("Booking page not found.")
            modules = (
                await db.execute(
                    select(TenantModule).where(
                        TenantModule.tenant_id == tenant.id,
                        TenantModule.enabled.is_(True),
                    )
                )
            ).scalars()
            module_rows = list(modules)
            cards = [
                Article(
                    Img(
                        src=BOOKING_VIEWS[item.module].get(
                            "card_image", BOOKING_VIEWS[item.module]["image"]
                        ),
                        alt="",
                        style="width:100%;height:150px;object-fit:cover;border-radius:13px;margin-bottom:16px",
                    ),
                    H2(MODULE_LABELS[item.module][0]),
                    P(MODULE_LABELS[item.module][1]),
                    A(
                        "Book now",
                        href=f"/book/{tenant.slug}/{item.module}",
                        cls="button",
                    ),
                    cls="module enabled",
                )
                for item in module_rows
            ]
        return Html(
            _head(f"Book with {tenant.name}"),
            Body(
                Div(
                    Nav(
                        A(Span("F", cls="mark"), tenant.name, href=f"/book/{tenant.slug}", cls="brand"),
                        A("Powered by FastBooking", href="/", cls="button outline"),
                        cls="nav",
                    ),
                    cls="nav-wrap",
                ),
                Main(
                    Section(
                        Span("Online bookings", cls="kicker"),
                        H1("What would you like to book?"),
                        P("Choose a service for live availability and a booking experience designed around it."),
                        cls="page-hero",
                    ),
                    Div(*cards, cls="feature-groups")
                    if cards
                    else P("Online booking is not enabled yet.", cls="empty"),
                ),
                _public_footer(),
            ),
        )

    @app.get("/book/{tenant_slug}/{module}")
    async def customer_journey(request, tenant_slug: str, module: str):
        if module not in BOOKING_VIEWS:
            return RedirectResponse(f"/book/{tenant_slug}", status_code=303)
        async with async_session_factory() as db:
            tenant = (
                await db.execute(
                    select(Tenant)
                    .join(TenantModule, TenantModule.tenant_id == Tenant.id)
                    .where(
                        Tenant.slug == tenant_slug,
                        Tenant.status == "active",
                        TenantModule.module == module,
                        TenantModule.enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if not tenant:
                return RedirectResponse(f"/book/{tenant_slug}", status_code=303)
            locations = {
                item.id: item
                for item in (
                    await db.execute(
                        select(Location).where(
                            Location.tenant_id == tenant.id,
                            Location.active.is_(True),
                        )
                    )
                ).scalars()
            }
            offerings = list(
                (
                    await db.execute(
                        select(Offering).where(
                            Offering.tenant_id == tenant.id,
                            Offering.module == module,
                            Offering.active.is_(True),
                        )
                    )
                ).scalars()
            )
            resources = list(
                (
                    await db.execute(
                        select(Resource).where(
                            Resource.tenant_id == tenant.id,
                            Resource.module == module,
                            Resource.active.is_(True),
                        )
                    )
                ).scalars()
            )
            room_types = list(
                (
                    await db.execute(
                        select(HotelRoomType).where(
                            HotelRoomType.tenant_id == tenant.id,
                            HotelRoomType.active.is_(True),
                        )
                    )
                ).scalars()
            ) if module == "hotel" else []
            event_rows = (
                await db.execute(
                    select(TicketType, ScheduledEvent)
                    .join(ScheduledEvent, ScheduledEvent.id == TicketType.event_id)
                    .where(
                        TicketType.tenant_id == tenant.id,
                        TicketType.active.is_(True),
                        ScheduledEvent.status == "published",
                    )
                )
            ).all() if module == "events" else []
            programmes = list(
                (
                    await db.execute(
                        select(RecreationProgramme).where(
                            RecreationProgramme.tenant_id == tenant.id,
                            RecreationProgramme.status == "published",
                        )
                    )
                ).scalars()
            ) if module == "recreation" else []

        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        guest_fields = (
            Label("Your name", Input(name="guest_name", required=True)),
            Label("Email", Input(type="email", name="guest_email", required=True)),
            Label("Phone", Input(type="tel", name="guest_phone")),
        )
        options = []
        forms = []
        if module == "restaurant":
            dining_locations = [
                location
                for location in locations.values()
                if any(resource.location_id == location.id for resource in resources)
            ]
            options = [
                (location.name, f"Tables for 2–{max((resource.capacity for resource in resources if resource.location_id == location.id), default=2)} guests")
                for location in dining_locations
            ]
            if dining_locations:
                forms.append(
                    Form(
                        Select(*[Option(location.name, value=location.slug) for location in dining_locations], name="location_slug"),
                        Label("Date", Input(type="date", name="date", value=tomorrow, required=True)),
                        Label("Time", Input(type="time", name="time", value="18:30", required=True)),
                        Label("Party size", Input(type="number", name="party_size", value="2", min="1", max="50", required=True)),
                        *guest_fields,
                        Label("Notes", Textarea(name="notes"), cls="wide"),
                        Button("Reserve table", type="submit", cls="button wide"),
                        method="post",
                        action=f"/book/{tenant.slug}/{module}",
                        cls="booking-form",
                    )
                )
        elif module == "hotel":
            options = [
                (room.name, f"Sleeps {room.occupancy} · {tenant.currency} {room.nightly_rate:,.2f} per night")
                for room in room_types
            ]
            if room_types:
                forms.append(
                    Form(
                        Label("Room type", Select(*[Option(room.name, value=str(room.id)) for room in room_types], name="room_type_id"), cls="wide"),
                        Label("Check in", Input(type="date", name="check_in", value=tomorrow, required=True)),
                        Label("Check out", Input(type="date", name="check_out", value=(datetime.date.today() + datetime.timedelta(days=2)).isoformat(), required=True)),
                        Label("Rooms", Input(type="number", name="quantity", value="1", min="1", max="20")),
                        *guest_fields,
                        Label("Notes", Textarea(name="notes"), cls="wide"),
                        Button("Reserve stay", type="submit", cls="button wide"),
                        method="post",
                        action=f"/book/{tenant.slug}/{module}",
                        cls="booking-form",
                    )
                )
        elif module == "events":
            options = [
                (event.name, f"{event.starts_at:%d %b · %H:%M} · {ticket.name} · {tenant.currency} {ticket.price:,.2f}")
                for ticket, event in event_rows
            ]
            if event_rows:
                forms.append(
                    Form(
                        Label("Event and ticket", Select(*[Option(f"{event.name} · {ticket.name}", value=str(ticket.id)) for ticket, event in event_rows], name="ticket_type_id"), cls="wide"),
                        Label("Tickets", Input(type="number", name="quantity", value="1", min="1", max="10")),
                        *guest_fields,
                        Label("Notes", Textarea(name="notes"), cls="wide"),
                        Button("Book tickets", type="submit", cls="button wide"),
                        method="post",
                        action=f"/book/{tenant.slug}/{module}",
                        cls="booking-form",
                    )
                )
        elif module == "clinic":
            practitioners = [item for item in resources if item.resource_type == "practitioner"]
            options = [
                (offering.name, f"{offering.duration_minutes or 30} minutes · {tenant.currency} {offering.price:,.2f}")
                for offering in offerings
            ]
            if offerings and practitioners:
                forms.append(
                    Form(
                        Label("Service", Select(*[Option(item.name, value=str(item.id)) for item in offerings], name="offering_id"), cls="wide"),
                        Label("Practitioner", Select(*[Option(item.name, value=str(item.id)) for item in practitioners], name="resource_id"), cls="wide"),
                        Label("Date", Input(type="date", name="date", value=tomorrow, required=True)),
                        Label("Time", Input(type="time", name="time", value="10:00", required=True)),
                        *guest_fields,
                        Label("Reason for visit", Textarea(name="notes"), cls="wide"),
                        Button("Request appointment", type="submit", cls="button wide"),
                        method="post",
                        action=f"/book/{tenant.slug}/{module}",
                        cls="booking-form",
                    )
                )
        else:
            options = [
                (item.name, f"{item.resource_type.title()} · capacity {item.capacity}")
                for item in resources
            ] + [
                (item.name, f"Programme · {item.starts_at:%d %b} · {max(0, item.capacity - item.enrolled)} places")
                for item in programmes
            ]
            if resources:
                forms.append(
                    Form(
                        Input(type="hidden", name="booking_kind", value="facility"),
                        H3("Reserve a facility"),
                        Label("Space", Select(*[Option(item.name, value=str(item.id)) for item in resources], name="resource_id"), cls="wide"),
                        Label("Date", Input(type="date", name="date", value=tomorrow, required=True)),
                        Label("Start", Input(type="time", name="time", value="17:30", required=True)),
                        Label("Minutes", Input(type="number", name="duration", value="60", min="30", max="480")),
                        *guest_fields,
                        Label("Notes", Textarea(name="notes"), cls="wide"),
                        Button("Reserve facility", type="submit", cls="button wide"),
                        method="post",
                        action=f"/book/{tenant.slug}/{module}",
                        cls="booking-form",
                    )
                )
            if programmes:
                forms.append(
                    Form(
                        Input(type="hidden", name="booking_kind", value="programme"),
                        H3("Join a programme"),
                        Label("Programme", Select(*[Option(item.name, value=str(item.id)) for item in programmes], name="programme_id"), cls="wide"),
                        *guest_fields,
                        Label("Notes", Textarea(name="notes"), cls="wide"),
                        Button("Enrol", type="submit", cls="button wide"),
                        method="post",
                        action=f"/book/{tenant.slug}/{module}",
                        cls="booking-form",
                    )
                )

        view = BOOKING_VIEWS[module]
        error = request.query_params.get("error", "")
        return Html(
            _head(f"{view['title']} · {tenant.name}"),
            Body(
                Div(
                    Nav(
                        A(Span("F", cls="mark"), tenant.name, href=f"/book/{tenant.slug}", cls="brand"),
                        A("All services", href=f"/book/{tenant.slug}", cls="button outline"),
                        cls="nav",
                    ),
                    cls="nav-wrap",
                ),
                Section(
                    Div(
                        Span(MODULE_LABELS[module][0], cls="kicker"),
                        H1(view["title"]),
                        P(view["lede"]),
                        cls="booking-hero-inner",
                    ),
                    cls="booking-hero",
                    style=f"background-image:url('{view['image']}')",
                ),
                Main(
                    Section(
                        H2("Available options"),
                        P("Availability is checked again when you submit."),
                        Div(*[Div(Strong(name), Span(meta), cls="option") for name, meta in options], cls="options")
                        if options
                        else P("No availability has been published yet.", cls="empty"),
                        P("Photo by ", A(view["credit"][0], href=view["credit"][1]), " on Unsplash", cls="photo-credit"),
                        cls="booking-panel",
                    ),
                    Section(
                        P(error, cls="notice") if error else None,
                        *forms if forms else [P("Online booking is not configured for this service yet.", cls="empty")],
                        cls="booking-panel",
                    ),
                    cls="booking-layout",
                ),
            ),
        )

    @app.post("/book/{tenant_slug}/{module}")
    async def submit_customer_booking(request, tenant_slug: str, module: str):
        if module not in BOOKING_VIEWS:
            return RedirectResponse(f"/book/{tenant_slug}", status_code=303)
        form = await request.form()
        name = str(form.get("guest_name", ""))
        email = str(form.get("guest_email", ""))
        phone = str(form.get("guest_phone", ""))
        notes = str(form.get("notes", ""))
        async with async_session_factory() as db:
            try:
                created = None
                if module == "restaurant":
                    location = (
                        await db.execute(
                            select(Location).join(Tenant, Tenant.id == Location.tenant_id).where(
                                Tenant.slug == tenant_slug,
                                Location.slug == str(form["location_slug"]),
                            )
                        )
                    ).scalar_one()
                    starts_at = datetime.datetime.fromisoformat(f"{form['date']}T{form['time']}").replace(tzinfo=ZoneInfo(location.timezone))
                    created = await create_restaurant_reservation(
                        db,
                        tenant_slug=tenant_slug,
                        location_slug=location.slug,
                        guest_name=name,
                        guest_email=email,
                        guest_phone=phone,
                        starts_at=starts_at,
                        party_size=int(form.get("party_size", 1)),
                        notes=notes,
                    )
                elif module == "hotel":
                    room = await db.get(HotelRoomType, int(form["room_type_id"]))
                    location = await db.get(Location, room.location_id) if room else None
                    if not room or not location:
                        raise BookingError("Room type not found")
                    created = await create_hotel_booking(
                        db,
                        tenant_slug=tenant_slug,
                        location_slug=location.slug,
                        room_type_id=room.id,
                        guest_name=name,
                        guest_email=email,
                        guest_phone=phone,
                        check_in=datetime.date.fromisoformat(str(form["check_in"])),
                        check_out=datetime.date.fromisoformat(str(form["check_out"])),
                        rooms=int(form.get("quantity", 1)),
                        notes=notes,
                    )
                elif module == "events":
                    row = (
                        await db.execute(
                            select(TicketType, ScheduledEvent)
                            .join(ScheduledEvent, ScheduledEvent.id == TicketType.event_id)
                            .where(TicketType.id == int(form["ticket_type_id"]))
                        )
                    ).one_or_none()
                    if not row:
                        raise BookingError("Ticket type not found")
                    ticket, event = row
                    location = await db.get(Location, event.location_id)
                    created = await create_event_booking(
                        db,
                        tenant_slug=tenant_slug,
                        location_slug=location.slug,
                        ticket_type_id=ticket.id,
                        guest_name=name,
                        guest_email=email,
                        guest_phone=phone,
                        quantity=int(form.get("quantity", 1)),
                        notes=notes,
                    )
                elif module == "clinic":
                    offering = await db.get(Offering, int(form["offering_id"]))
                    location = await db.get(Location, offering.location_id) if offering else None
                    if not offering or not location:
                        raise BookingError("Clinic service not found")
                    starts_at = datetime.datetime.fromisoformat(f"{form['date']}T{form['time']}").replace(tzinfo=ZoneInfo(location.timezone))
                    created = await create_clinic_booking(
                        db,
                        tenant_slug=tenant_slug,
                        location_slug=location.slug,
                        offering_id=offering.id,
                        practitioner_resource_id=int(form["resource_id"]),
                        guest_name=name,
                        guest_email=email,
                        guest_phone=phone,
                        starts_at=starts_at,
                        notes=notes,
                    )
                elif form.get("booking_kind") == "programme":
                    programme = await db.get(RecreationProgramme, int(form["programme_id"]))
                    location = await db.get(Location, programme.location_id) if programme else None
                    if not programme or not location:
                        raise BookingError("Programme not found")
                    created = await enrol_in_programme(
                        db,
                        tenant_slug=tenant_slug,
                        location_slug=location.slug,
                        programme_id=programme.id,
                        guest_name=name,
                        guest_email=email,
                        guest_phone=phone,
                        notes=notes,
                    )
                else:
                    resource = await db.get(Resource, int(form["resource_id"]))
                    location = await db.get(Location, resource.location_id) if resource else None
                    if not resource or not location:
                        raise BookingError("Facility not found")
                    starts_at = datetime.datetime.fromisoformat(f"{form['date']}T{form['time']}").replace(tzinfo=ZoneInfo(location.timezone))
                    created = await create_facility_booking(
                        db,
                        tenant_slug=tenant_slug,
                        location_slug=location.slug,
                        resource_id=resource.id,
                        offering_id=None,
                        guest_name=name,
                        guest_email=email,
                        guest_phone=phone,
                        starts_at=starts_at,
                        ends_at=starts_at + datetime.timedelta(minutes=int(form.get("duration", 60))),
                        notes=notes,
                    )
                await db.commit()
                return RedirectResponse(f"/manage/{created.manage_token}?created=1", status_code=303)
            except (BookingError, KeyError, TypeError, ValueError) as exc:
                await db.rollback()
                message = str(exc) if isinstance(exc, BookingError) else "Please check the booking details and try again."
                return RedirectResponse(f"/book/{tenant_slug}/{module}?error={quote(message)}", status_code=303)

    @app.get("/manage/{manage_token}")
    async def manage_booking(request, manage_token: str):
        token_hash = hashlib.sha256(manage_token.encode()).hexdigest()
        async with async_session_factory() as db:
            booking = (
                await db.execute(
                    select(Booking).where(Booking.manage_token_hash == token_hash)
                )
            ).scalar_one_or_none()
            if not booking:
                return landing_page("Booking management link is invalid.")
            tenant = await db.get(Tenant, booking.tenant_id)
            location = await db.get(Location, booking.location_id)
            display_timezone = ZoneInfo(location.timezone if location else tenant.timezone)
            starts_at = booking.starts_at.astimezone(display_timezone)
            ends_at = booking.ends_at.astimezone(display_timezone)
        return Html(
            _head(f"Manage {booking.public_reference}"),
            Body(
                _public_nav(),
                Main(
                    P("Your booking is confirmed.", cls="success")
                    if request.query_params.get("created")
                    else None,
                    H1(f"Booking {booking.public_reference}"),
                    P(f"Status: {booking.status.title()}"),
                    P(
                        f"{starts_at:%d %b %Y %H:%M} – "
                        f"{ends_at:%d %b %Y %H:%M} · {location.name if location else tenant.name}"
                    ),
                    Form(
                        Button("Cancel booking", cls="button", type="submit"),
                        method="post",
                        action=f"/manage/{manage_token}/cancel",
                    )
                    if booking.status in {"pending", "confirmed"}
                    else None,
                    P(
                        "To choose a new time, cancel this booking and make a new "
                        "conflict-checked reservation."
                    ),
                    A("Return to booking page", href=f"/book/{tenant.slug}"),
                    cls="shell",
                ),
                _public_footer(),
            ),
        )

    @app.post("/manage/{manage_token}/cancel")
    async def cancel_managed_booking(manage_token: str):
        async with async_session_factory() as db:
            try:
                await cancel_booking(db, manage_token)
                await db.commit()
            except BookingError:
                await db.rollback()
        return RedirectResponse(f"/manage/{manage_token}", status_code=303)
