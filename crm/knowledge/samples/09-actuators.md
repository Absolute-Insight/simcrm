---
title: Actuators, gearboxes and switch boxes
category: Actuation & instrumentation
tags: actuator, electric actuator, pneumatic actuator, hydraulic actuator, rack and pinion, scotch yoke, spring return, double acting, fail safe, fail close, fail open, gearbox, bevel gearbox, worm gearbox, declutchable, switch box, limit switch box, position indicator, solenoid valve, namur, ISO 5211, torque, multi-turn, quarter-turn, modulating, on-off
---
*Sample content — replace with your own product knowledge.*

## What it is

An actuator turns a valve remotely or automatically. It is selected by the valve's motion (quarter-turn for ball, butterfly and plug valves; multi-turn for gate and globe; linear for control valves), by the torque or thrust the valve needs, and by the power available on site.

- **Pneumatic** actuators run on instrument air, typically 4–7 bar. **Rack and pinion** units are compact and cheap for small quarter-turn valves; **scotch yoke** units give high torque at the ends of stroke for large valves. **Double-acting** actuators need air to move both ways; **spring-return** actuators use air one way and springs the other, so the valve fails to a known position on loss of air. A **solenoid valve** (often NAMUR-mounted directly on the actuator) switches the air, and a **switch box** with limit switches or a position transmitter reports open and closed back to the control system.
- **Electric** actuators use a motor and gear train with integral torque and position limits, local controls and a hand-wheel for manual override. On–off, modulating (4–20 mA) and fieldbus versions exist. A fail-safe electric actuator needs a spring or battery pack.
- **Hydraulic** actuators give very high force in a small envelope for large or high-pressure valves, and electro-hydraulic units combine a small power pack with an electric supply.
- **Gearboxes** (bevel for gate and globe, worm for quarter-turn) reduce the effort on a manual valve and are often the mounting between an actuator and a large valve. Declutchable gearboxes allow manual override of an automated valve.

## Typical sizes and ratings

- Quarter-turn pneumatic: about 5 Nm to 100,000 Nm; electric quarter-turn to several thousand Nm; multi-turn electric to tens of thousands of Nm and hundreds of rpm-turns.
- Mounting to ISO 5211 flanges (F03 to F60) so a valve and actuator from different suppliers fit.
- Electric supplies of 24 V DC, 230 V or 400 V three-phase; enclosure ratings IP67 / IP68; explosion-proof (Ex d) versions for hazardous areas.
- Duty class: on–off (S2), modulating (S4) — modulating duty needs a motor rated for the starts per hour.

## Materials

Pneumatic bodies in anodised or coated aluminium; stainless or nickel-plated for corrosive and food plants. Electric housings in aluminium alloy, epoxy coated. Gearbox bodies in ductile iron. Springs and pinions in alloy or stainless steel.

## Where it is used

- **Water and wastewater:** electric actuators on large gate and butterfly valves at pump stations and treatment works; SCADA integration.
- **Mining and minerals processing, mining slurry:** pneumatic cylinders and electric actuators on knife gates; heavy-duty enclosures for dust and wash-down.
- **Petrochemical and refining:** spring-return pneumatic on emergency shutdown valves; Ex-rated electrics on tank farms.
- **Power generation and steam:** modulating electric actuators on feedwater and drain valves.
- **Food and beverage, pulp and paper:** stainless rack-and-pinion actuators with switch boxes on process and CIP valves.
- **Fire protection:** supervised switch boxes reporting valve position on sprinkler isolation.

## Strengths and limits

Pneumatic: simple, cheap, inherently fail-safe with springs, safe in hazardous areas — but needs clean dry air and gives limited position control without a positioner. Electric: precise, self-contained, easy to integrate — but slower, needs power, and fail-safe costs extra. Hydraulic: highest force — but needs a power pack and maintenance. Always size on the valve's break-to-open torque with a safety factor (commonly 25–30%), at the minimum available supply pressure.

## Questions to ask the customer

- Which valve — type, size, class, and its torque figure? If unknown, ask for make and model.
- What power is available at the valve: instrument air (at what pressure), 24 V DC, 230 V, 400 V?
- Fail position required on loss of power or air?
- On–off or modulating? What signal and feedback (limit switches, 4–20 mA, fieldbus)?
- Hazardous area? Outdoor, wash-down or corrosive environment?

## Standards

ISO 5211 (part-turn actuator attachment), ISO 5210 (multi-turn actuator attachment), EN 15714 (industrial valve actuators), NAMUR VDI/VDE 3845 (solenoid and switch box mounting interface), IEC 60529 (IP ratings), IEC 60079 / ATEX / IECEx (hazardous-area equipment), IEC 61508 (SIL-rated fail-safe actuators).
