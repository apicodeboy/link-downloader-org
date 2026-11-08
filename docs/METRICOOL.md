# Publishing and Metricool

The app includes a publishing **preparation** system. You can pick a downloaded or
processed video, edit its caption, add hashtags, choose destination accounts, and save a
publishing job. You then approve your own draft. Nothing is ever posted automatically.

## What works today

| Step | Status |
| --- | --- |
| Create a draft from a video | Works |
| Caption prefilled from the original post (editable) | Works |
| Hashtags, destination accounts, optional schedule time | Works |
| Admin approval (any edit removes the approval) | Works |
| Download a "publish package" (MP4 + `caption.txt`) | Works |
| Test the Metricool connection (read-only call) | Works once configured |
| Automatic submission to Metricool | **Not enabled** (see below) |

The publish package is the recommended path for now. Download it and upload it in
Metricool's planner by hand.

## What has been verified in Metricool's official documentation

Source: [Basic guide for API integration](https://help.metricool.com/basic-guide-for-api-integration-r97af).

* API access is only included on the **Advanced** and **Custom** plans.
* Base URL `https://app.metricool.com/api`. Every request sends the header
  `X-Mc-Auth: <your API token>` plus the `userId` and `blogId` query parameters.
* The token is in Metricool under **Account Settings > API**.
* `GET /admin/simpleProfiles?userId=…` lists your brands (each has a `blogId`).
* `POST /v2/scheduler/posts?blogId=…&userId=…` creates a scheduled post. It needs
  `publicationDate`, `text` and at least one entry in `providers`.
* Media must be at a **public URL that does not expire**. It is normalized through
  Metricool first. Without a valid media ID, the post is scheduled **without** the media.

## Why automatic submission is switched off

1. **Media hosting conflict.** This app keeps each visitor's videos private to their browser and deletes
   them after 60 minutes. Metricool needs a public, permanent URL. Making videos public is
   a separate security decision you should make on purpose.
2. **The video upload flow isn't verified.** The guide documents media normalization with
   an image example. Video-specific requirements are in the Swagger files and the "Common
   questions and errors" article, which still need checking against your plan.
3. **Account permissions vary.** The destinations a brand can post to depend on which
   networks you connected in Metricool.

`MetricoolProvider.submit()` in [backend/app/publishing/providers.py](../backend/app/publishing/providers.py)
therefore refuses with a clear message instead of guessing.

## Connecting your account (read-only test)

1. Confirm your plan includes API access.
2. Copy your token, `userId` and `blogId` (both IDs appear in the browser address bar
   when a brand is open in Metricool).
3. Add them to `/etc/video-downloader/video-downloader.env`:

   ```ini
   PUBLISHING_PROVIDER=metricool
   METRICOOL_USER_TOKEN=paste-token-here
   METRICOOL_USER_ID=123456
   METRICOOL_BLOG_ID=654321
   PUBLISHING_ACCOUNTS=[{"id":"ig-main","network":"instagram","label":"@yourbrand"}]
   ```

4. Restart: `sudo systemctl restart video-downloader-api`
5. On the **Publish** page, click **Test connection**. It only reads your brand list.

`PUBLISHING_SUBMIT_ENABLED` stays `false` until submission is implemented and you
choose to turn it on.

## Finishing the integration later

1. Decide how videos become publicly reachable. For example, use a separate bucket with
   long-lived, unguessable URLs, published only for approved jobs.
2. Verify the video flow in Metricool's Swagger docs (linked from the guide above).
3. Implement `MetricoolProvider.submit()`: normalize the media URL, then call
   `POST /v2/scheduler/posts` with `publicationDate`, `text` (caption + hashtags),
   `providers` and the media ID.
4. Add tests with a fake HTTP opener, like `test_metricool_connection_check_uses_documented_endpoint`.
5. Set `PUBLISHING_SUBMIT_ENABLED=true`. Submission still requires an approved job and an
   administrator to click **Submit**.
