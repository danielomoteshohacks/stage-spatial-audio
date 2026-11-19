# Running the blind spatial test with friends

This tests the spatialisation profiles of decision 0007. Each profile adds one thing:
V1 front-arc limit, V2 pinna, V3 directional-band EQ, V4 room reflections, V5 late reverb.
All files are loudness-matched, so loudness is never the reason one wins.

## Before anyone listens (you, once)

```
python scripts/make_abx.py render path/to/clip.wav --start 30 --seconds 15
```

- Pick a clip you own or may use. Never use Spotify audio.
- The command writes `abx/01.wav` to `abx/06.wav` and `abx/key.json`.
- **Do not let listeners see `key.json`.** You running the test may know the key; the listeners must not.
- The WAVs are ignored by Git. Never commit them.
- To try the combined profile as well, add `--profiles V0 V1 V2 V3 V4 V5 max`.

## Each listener

1. Use headphones, not speakers, and write down the model.
2. Use a quiet room. Set the volume once on any file, then leave it alone.
3. Listen to every file as often as they like, in any order.
4. Answer three questions:
   - Rank all files from best to worst.
   - Which file sounded most **outside your head**, as if coming from around you rather than
     from between your ears?
   - Which file sounded most **natural**?
5. Record the answers:

```
python scripts/make_abx.py rank --session abx --listener L01 --headphones "Sony MDR-7506"
```

The script asks the three questions. Use an ID such as `L01`, not a name. Each answer is
appended to `experiments/results.csv`, already decoded from file numbers to profiles.

## How many listeners

- Ten or more listeners make a first result. Report it with an interval, not just "most people
  preferred". At ten, only a large effect will show.
- Make a new session (run `render` again) for every few listeners, so the numbers get reshuffled.

## Reading the result

- The objective proxies in decision 0007 only show that a cue is present in the signal. This test
  decides whether anyone hears it, and whether it is better.
- Report every outcome, including "nobody could tell" and "V0 won". Those results are as useful as
  a win.
