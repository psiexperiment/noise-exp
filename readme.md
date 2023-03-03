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

    pip install cfts[ni]

For use with TDT hardware:

    pip install cfts[tdt]
