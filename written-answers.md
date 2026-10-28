1.For rolling update, let’s say we have 3 samples, 2 is old version, 1 is new version. 
If display_name is deleted, the old samples will fail because they still query display_name.
Solution: We should add this new column first, and do not delete old column, then we ship the V1 with these two column exist. When we update data, we update both column. After all the update V1 of application finish, we change to read the new column and ship as V2. After we test V2, we ship V3 and don’t update old column this time. Finally, we test V3 and delete old column.

2. TTL 5s, which means if the next query comes within 5s, still get the wrong ACTIVE. Or if request A stuck for a while, will cause a bigger issue. 
Solution: The simplest way is not to cache the status but just cache the information.

3. Since service A only has 50 worker, 1000(rps) * 20/1000(s) = 20 per workers are needed for /report. When timeout, 1000(rps) * 100/1000(s) = 100 per workers > 50 workers. 
And with 3 retries, 100/1000(s)=> (1+3) * 100 / 1000(s) = 400/1000(s), 400 per workers > 50 workers.
Workers run out and has more to wait, the queue will be full.
Solution: Only give 25 worker for /report. When workers run out, immediately response failure. If failure accumulate, shut down the request for couples of seconds. 
So, when B is unhealthy, return 503. Or if application can accept, return the most recent cache.