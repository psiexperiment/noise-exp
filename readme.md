# Noise exposure

## Introduction

This provides basic noise-exposure functionality for hearing loss experiments.

This package nominally supports both National Instruments and TDT hardware.
Those using National Instruments hardware will have to do some setup work to
map the appropriate inputs and outputs as well as ensure that all devices are
running off of the same sample clock (to ensure precise timing).

For TDT hardware, only the RZ6 is currently supported. Fortunately, the RZ6 is a fairly standard piece of hardware and should be plug-and-play out of the box.

## Installing

Install your preferred Python distribution. For use with National Instruments hardware:

    pip install noise-exp[ni]

For use with TDT hardware:

    pip install noise-exp[tdt]

For use with a sound card:

    pip install noise-exp[soundcard]

## Configuring

The cohort is entered by clicking the cohort button in the launcher, which
opens one field per slot in the exposure cage. Six slots are offered by
default. If your cage holds a different number of animals, set:

    NOISE_EXP_MAX_ANIMALS=4

The microphone and speaker each take a calibration picked in the launcher,
as in the cfts and abts launchers: one on file in cftscal, or a nominal
sensitivity (mV/Pa for the microphone, dB SPL at 1 Vrms for the speaker) when
none has been measured, or unity for the microphone.

Video of the exposure is recorded with psivideo when "Record" is ticked next
to Video in the launcher (the default). The exposure then waits for psivideo
to be running. Untick it to run where there is no camera; set
`NOISE_EXP_RECORD_VIDEO=false` (or use File > Set Defaults) to make that the
default on a machine.

## Exposure level

The noise is scaled so that its level through the speaker calibration is the
level asked for. Exposures run before November 2026 scaled it differently
(see `legacy_level` in psiaudio's `BandlimitedFIRNoiseFactory`), which
usually missed the level by several dB. To repeat one of those exposures
exactly, set "legacy level scaling" to "yes" in the Exposure settings in the
experiment window. It is saved with the data, like the other settings.

## Level control

The monitor microphone is the ground truth, but it sits elsewhere in the
booth than where the speaker was calibrated, so it can read a few dB off
target, and the level can drift. "Hold ... level at target" (on by default)
adjusts the exposure's gain from the microphone's level, measured in the
exposure band (the default) or overall. At exposure levels, ambient sound
and the animals add little to the overall level, so either works; the band
level is the one psiaudio sets.

* The exposure starts at the gain set by "Start with a trim of ... dB" (0 by
  default). Use it for your own pre-calibration of the booth: it applies
  whether or not the level is controlled, and the loop's corrections are
  made about it.
* After the first window (10 s by default), it trims the gain so the band
  level is at target, by at most the "at the start" limit (6 dB). A trim of
  more than 3 dB is reported: the speaker calibration (or your trim) may need
  redoing.
* From then on, it corrects drift, half the remaining error at a time, by at
  most the "after" limit (2 dB) on top of the trim.

The loop also measures during the top 6 dB of the onset ramp (about its
second half), comparing each second with the ramp's level then. While the
ramp is playing, it trims on as few as 3 s, early enough for the trim to
reach the speaker before the exposure is at full level. For that, the ramp's
second half has to last about 3 s plus the seconds the output buffers ahead,
plus a second. A shorter ramp still trims as early as it can. If fewer than
3 s of the ramp can be measured (e.g., the 1 s default), the first trim comes
after a full window, and the exposure plays at the untrimmed level until
then.

Each window's level is the median of its 1 s levels, so brief noises from
the animals don't move the gain, and only seconds played at the gain last set
count. The loop stops and holds the gain (shown as FROZEN under "Level
correction") if the level is more than 10 dB below target (check the
microphone) or the drift correction stays at its limit. If the level is more
than 6 dB above target for 3 s, the exposure is turned down by the full
range of the correction and the loop stops. Every decision is saved with the
data in `level_control.csv`.

The loop is off when "legacy level scaling" is on, since that repeats an
earlier, uncontrolled exposure (the trim, if not 0, still applies).

The level plot shows the overall level (black) and the level in the exposure
band (green). The faint lines are the 1 s levels; the bold lines are their
running median over the level control's window (10 s by default), which is
what the loop judges. The plot spans the target level ± 3 dB.
