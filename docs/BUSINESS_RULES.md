# Business Requirements Document (BRD)

**Project Name:** Night Crawler – Foodservice Venues
**Role Scope:** Technical Assessment / Crawling Engineer

---

## 1. Project Overview & Vision

The goal is to design, implement, and operate a robust, reusable, and maintainable web crawling platform. The system must run recurrently to continuously discover, extract, and update foodservice data while maintaining high data quality, avoiding duplicates, and minimizing unnecessary web requests.

---

## 2. Core Business Objectives

* **Data Freshness:** Periodically re-crawl target sources to update existing venue profiles, menus, and reviews without duplicating records.
* **High Coverage & Discovery:** Implement robust search/geographical discovery strategies to find all relevant target establishments with minimal missing entries.
* **System Resilience:** Gracefully handle transient errors, partial pipeline failures, anti-bot/rate-limiting restrictions, and resume interrupted crawl jobs seamlessly.
* **Scalability:** Ensure the underlying architecture can easily scale as the number of data sources, target locations, and execution frequencies increase.

---

## 3. Scope of Work

### Task 1: Google Maps (Mandatory)

Discover and extract all foodservice venues (restaurants, bars, fast food, etc.) operating in **Andorra**.

* **Target Fields per Venue:**
  * **Basic Info:** Name, address, venue categories/tags, phone number, website, reservation link, menu link.
  * **Metrics & Activity:** Rating, total review count, price range/category, popular times/live occupancy.
  * **Attributes:** Accessibility, amenities, service options, highlights, payment options, dining options, and "About" details.
  * **Structured Menu:** Detailed menu sections and item descriptions where available.
* **Target Fields per Review:**
  * Reviewer name, star rating, exact/approximate publication date, and review text.
  * Explicit relation linking each review to its corresponding venue.

### Task 2: Platform Crawler (Choose 1 Option)

* **Option A – TheFork (`thefork.es`):** Build a functional crawler extracting Name, Address, Opening Hours, and Structured Menu for at least **100 restaurants**.
* **Option B – OpenTable (`opentable.es`):** Build a functional crawler extracting Name, Address, Services/Amenities, and Structured Menu for all restaurants in **Barcelona**.

---

## 4. Technical & Architectural Requirements

### System Modules & Functional Responsibilities

1. **Discovery:** Automated discovery of unknown establishments and re-queuing of previously saved targets.
2. **Fetching & Dynamic Content:** Support dynamic rendering (JavaScript execution, infinite scrolling, pagination, dynamic tabs).
3. **Parsing & Normalization:** Robust extraction rules that handle missing fields cleanly (saving `null` or equivalent without failing the job).
4. **Deduplication & Change Detection:** Logic to detect whether a venue already exists and evaluate if data has changed before running updates.
5. **Fault Tolerance:** Retry mechanisms for transient HTTP errors, checkpointing to resume interrupted executions, and error isolation.
6. **Logging & Monitoring:** Execution tracking, crawl run durations, error rates, and metrics.

---

## 5. Data & Persistence Requirements

* **Database Choice:** **MongoDB** is preferred.
* **Data Schemas:** Must maintain clear relationships between entities:
  * `Venues`
  * `Reviews`
  * `Menus`
  * `CrawlExecutions` / `Metadata` (timestamps, status, run IDs)

---

## 6. Deliverables Checklist

1. **Source Code:** Modular, clean, readable code separating fetching, parsing, persistence, and schedule execution.
2. **Technical Documentation:**
   * Architecture overview and component breakdown.
   * Setup, installation, and run instructions.
   * Strategy explanations: discovery, deduplication, incremental updates, resuming jobs, and dynamic content handling.
   * Known limitations and technical trade-offs made during development.
3. **Database Dump:** Database export containing populated entities and crawl execution history.

---

## 7. Key Success & Evaluation Criteria

* **Completeness & Accuracy:** High percentage of required fields captured accurately.
* **Recurrence Capabilities:** Ability to perform efficient delta updates and avoid re-scraping unchanged data.
* **Robustness & Recovery:** Graceful handling of edge cases, dynamic components, network failures, and interrupted runs.

## 8. Authentication Abuse Protection

* Failed logins are counted by normalized email and source IP in Redis.
* Five failed logins for one email, or 20 from one IP, temporarily block
  further login attempts for the remainder of the 15-minute window.
* Successful login clears the email's failed-login counter.
* Registration is limited to 10 attempts per source IP per 15-minute
  window, including successful registrations.
* Blocked requests receive HTTP 429 with a clear validation message.
  If Redis is unavailable, authentication fails closed with HTTP 502.
