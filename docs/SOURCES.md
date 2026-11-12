# Source documents

Operator 2026-11-12: "you always check source documents first"; no change is made "based on a
belief"; the documents "should be checked periodically".

A question of fact is answered from the source listed here, read that turn and cited, before any
measurement of ours. A source read again gets a new `read` date and a new `again by` date in the
same change. A source that answers a new question is added with the question it settles.
`tests/test_source_register_v1.py` fails when a listed file is missing, a date is not a date, or a
source is past its `again by` date.

`saved` is the copy in this repository; `link only` is a document this repository holds no copy
of, with why.

| id | settles | source | where | saved | read | again by |
|---|---|---|---|---|---|---|
| schwab-market-data-spec | what Schwab's REST endpoints send and accept | Schwab, Market Data API specification | docs/schwab/schwab_market_data_api_spec.pdf | saved | 2026-11-12 | 2026-12-12 |
| schwab-chains-quotes-parameters | the documented parameters of /chains and /quotes | Schwab, Market Data API | docs/schwab/schwab_market_data_parameters_chains_quotes.txt | saved | 2026-11-12 | 2026-12-12 |
| schwab-pricehistory-markets-parameters | the documented parameters of /pricehistory and /markets | Schwab, Market Data API | docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt | saved | 2026-11-12 | 2026-12-12 |
| schwab-streamer-guide | the stream's services, fields, delivery and response codes | Schwab, Streamer API guide | docs/schwab/schwab_streamer_api.pdf | saved | 2026-11-12 | 2026-12-12 |
| schwab-support-2026-10-06 | 300 symbols recommended per service, 120 requests a minute for non-order endpoints, large chains split by filters | Schwab support, emails | docs/schwab/schwab_support_emails_2026_10_06.txt | saved | 2026-11-12 | 2026-12-12 |
| schwab-support-2026-10-12 | LEVELONE services hold up to 3,000 symbols, open interest is the prior trading day's | Schwab support, emails | docs/schwab/schwab_support_emails_2026_10_12.txt | saved | 2026-11-12 | 2026-12-12 |
| occ-listing-procedures-plan | an exchange may add an option series on the same trading day, so a ticker's contract list can change inside a session | OCC, Options Listing Procedures Plan | https://theocc.com/getmedia/198bfc93-5d51-443c-9e5b-fd575a0a7d0f/options_listing_procedures_plan.pdf | link only: OCC's document, not ours to copy | 2026-11-12 | 2026-12-12 |
| sec-34-60365 | exchanges add series during the standard trading session ("intra-day add-on series"), within a strike price range | SEC, Release 34-60365 (https://www.sec.gov/files/rules/sro/nms/2009/34-60365.pdf) | docs/sources/sec_34-60365.pdf | saved | 2026-11-12 | 2026-12-12 |
| sec-34-67862 | additional strikes may be listed until the second business day before expiration | SEC, Release 34-67862, NYSE MKT (https://www.sec.gov/files/rules/sro/nysemkt/2012/34-67862.pdf) | docs/sources/sec_34-67862.pdf | saved | 2026-11-12 | 2026-12-12 |
| cboe-rg95-067 | Cboe's 1995 practice for strikes added during the day; the current Cboe rule is not read yet | Cboe, Regulatory Circular RG95-67 | https://cdn.cboe.com/resources/regulation/circulars/regulatory/RG95-067.pdf | link only: Cboe's document, not ours to copy | 2026-11-12 | 2026-12-12 |
| occ-daily-open-interest | open interest is calculated after the day's opening and closing trades are cleared, once a day | OCC, Daily Open Interest; Options Industry Council, General Information | https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/daily-open-interest | link only: OCC's page, not ours to copy | 2026-11-12 | 2026-12-12 |
| trading-hours-2026-12-06 | 23 hours a day, five days a week trading on the national exchanges from 2026-12-06; whether the date has held is not confirmed | WilmerHale client note of 2026-09-29 on the SEC's approval orders; the orders themselves are not read yet | https://www.wilmerhale.com/en/sitecore/content/whlaunch/home/research/news-publications/20260929-23x5-trading-comes-to-us-exchanges-what-firms-should-know-before-launch | link only: a law firm's note, not ours to copy; the SEC's orders are to be read and listed | 2026-11-12 | 2026-11-30 |
