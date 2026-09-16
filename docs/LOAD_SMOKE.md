# Load smoke test: the sale endpoint

**What this is.** A recorded measurement of the sale path under concurrent use, on one machine, taken
so that a later change can be compared against a number rather than an opinion. It is a smoke test,
not a capacity plan: the requests go through the real ASGI application - middleware, authorization,
service, database - but over an in-process transport rather than a socket, so the network, TLS and the
load balancer are not part of the measurement.

**How to reproduce:**

```
make load-smoke                     # 200 sales, 20 in flight
python backend/scripts/load_smoke_sale.py --sales 500 --concurrency 25
```

The script registers a throwaway business, creates one product, stocks it, and records N sales
concurrently, each with its own operation identifier. It exits non-zero if any request failed, and it
reads the application's own request counter back afterwards, so a client-side number cannot be
reported by a server that dropped half the requests.

---

## 1. The environment

| | |
|---|---|
| Machine | Intel Core i7-4600U @ 2.10 GHz, 4 threads, 15.9 GB RAM |
| Everything on one host | application process and database on the same machine, no container limits |
| Database | PostgreSQL 16.14, local cluster, `max_connections=100`, `shared_buffers=128MB` (default), `synchronous_commit=on` |
| Connection pool | defaults: `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=5` |
| Database role | the local development role, which is a **superuser** and therefore bypasses the Row-Level Security policies. See section 4 |
| Date | 2026-09-15 |

## 2. The numbers

Three runs, same code, same machine, same database, one after another.

| Run | Sales | Concurrency | Wall clock | Throughput | p50 | p95 | p99 | max | Failures |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 200 | 20 | 8.08s | 24.7 sales/s | 642 ms | 1437 ms | 2164 ms | 2522 ms | 0 |
| 2 | 200 | 20 | 8.17s | 24.5 sales/s | 700 ms | 1403 ms | 2208 ms | 2300 ms | 0 |
| 3 | 100 | 5 | 3.55s | 28.2 sales/s | 142 ms | 343 ms | 435 ms | 586 ms | 0 |

Runs 1 and 2 are within 3 percent of each other on throughput and latency, which is what makes the
number usable as a reference. The application's own counter agreed with the client in every run: 210
requests on the sale route for runs 1 and 2 (200 measured plus 10 warm-up), 110 for run 3.

## 3. What the numbers say

**Throughput is flat while latency grows with concurrency.** Four times the concurrency (5 to 20)
produced roughly the same 25 to 28 sales per second, while p50 latency grew five-fold. That is the
signature of saturation rather than of a slow path: the work per sale is constant, and the requests
queue for one resource. On this machine that resource is the single PostgreSQL instance on two
physical cores, not the application process, which is idle enough to answer all twenty in-flight
requests.

**A sale is one transaction.** The endpoint writes the sale, its lines, its payments, the stock
movement, the ledger entry, the receipt counter and the audit event in one unit of work, so the cost
is dominated by the number of rows and indexes touched rather than by round trips. That is deliberate:
a half-recorded sale is not an acceptable outcome, and the price of it is paid here.

**Zero failures at both concurrency levels**, including no `429`s: the run configures the write limit
at its ceiling and prints it, because a limit below the run's own throughput would have turned this
into a measurement of the rate limiter. The default limit is 120 writes per minute, which is a
protection for the service and is unchanged by this document.

**What this does not say:** it is not a capacity figure for a deployment. There is no network, no TLS
termination, no load balancer, no container CPU limit, no managed-database network hop, and no
concurrent traffic from anything else. The same code against a managed PostgreSQL instance on a
network will be slower per request and much better at parallelism. The number to remember is the
*shape* - flat throughput with rising latency once the database saturates - and the absolute figure
of 25 to 28 sales per second on one laptop.

## 4. What is not covered

- **Row-Level Security is not exercised.** The local role is a superuser, so the policies do not
  apply; a deployment runs as a role the policies bind, and this measurement does not include the
  predicate they add to every query.
- **No storage calls.** The sale path touches none. Uploads are a different path with a different
  profile (network, breaker, bulkhead) and are not measured here.
- **Short runs.** A few seconds each. This is not a soak test: nothing here would reveal a leak that
  needs hours to appear.
- **One writer process.** The in-process transport runs one event loop, so the number says nothing
  about behaviour with several instances against one database.

## 5. When to re-run

After any change to the sale path, the ledger or the inventory movement, and after any change to the
unit of work - the last of which now writes the tenant scope into every transaction. A comparison is
most useful when the invocation is identical: `--sales 200 --concurrency 20` against the same local
database, and read the p95 rather than the mean, because the mean hides exactly the queueing this
measurement exists to show.
