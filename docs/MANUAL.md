# Manual

How to instruct AI properly to make video editing more efficient.

## Timelines

## Clips

- Positioning terminology:
  - Where the clip sits on the timeline: **record in** (or timeline in / clip start)
  - Where the clip ends on the timeline: **record out**
  - Which moment of the video the clip begins with: **source in** (or in point)
  - Which moment of the video the clip ends on: **source out** 
- Editing terminology:
  - **Trim the head** (or trim the start): changes the source in and the record in together. The clip gets shorter from the front.
  - **Slip**: changes the source in and source out together, while the clip keeps its record in, record out and length. It's like sliding the video "under" the clip. It needs spare video past the end of the clip.
  - **Move**: shifts the whole clip on the timeline without changing which part of the video it shows.
  - **Ripple trim**: a trim that also pulls everything after it earlier, so no gap is left.


## Captions

You may want to:
- **Add caption**: Ask AI to add "TEXT" at *[TIME]* to *[TIME]*. You can also add details.
  Example: `Add "HELLO WORLD" centered at 00:05 to 00:10`
- **Remove caption**: Ask AI to remove caption at *[TIME]*. A backup is made and the caption's own timeline stays for it; say "and its timeline" to delete that too, without a backup.
- **Clean up captions**: Ask AI to delete unused caption timelines, e.g. after deleting captions or backups by hand.
- **Edit caption**: Ask AI to change text or any other property of caption at *[TIME]*.
- **Move caption**: Ask AI to change start time of caption at *[TIME]* by *[INTERVAL]*. Unless specified otherwise, all captions after this one on same timeline will be moved too.
  Example: `Move caption at 01:35 by +3s`
- **Turn Text+ titles into captions**: Ask AI to replace Text+ titles (all, on a track, or between *[TIME]* and *[TIME]*) with captions. They keep text, timing, look and fades, and can then be moved by AI. Drag a fade handle on each new caption by hand once, or its fades are lost when Resolve restarts.
  Example: `Replace all Text+ on V2 with captions`
- **Copy a look**: Ask AI to add a caption styled like the one at *[TIME]*.
- **Dark box behind text**: Ask AI to add captions with a dark box behind the text. By default it's black at 40 %, one box per line, with slightly rounded corners; say if you want it darker, one box for the whole caption, more padding or other corners.
  Example: `Add "HELLO WORLD" at 00:05 to 00:10 with a dark box behind it`