# Agent Ontology: 2D Rigid Body Statics

This file defines every key term used across the agent system. All agents must use these definitions consistently. When generating explanations for students, agents should use these definitions as ground truth.

---

## Free-Body Diagram (FBD)

A diagram of a single rigid body — isolated from all other bodies and supports — showing every external force and moment acting on it. Internal forces (between parts of the same body) are not shown. The body itself may be drawn as a simple outline or a box. An FBD is the prerequisite for writing equilibrium equations.

---

## Reaction

A force or moment exerted on the body by a support in response to the body's tendency to move. Reactions are the unknowns that equilibrium equations solve for. Every reaction corresponds to a degree of freedom that the support removes:
- A support that prevents translation in one direction produces one reaction force in that direction.
- A support that prevents rotation produces one reaction moment.

---

## Support Types

### Pin (Hinge)
Connects the body to a fixed point. Prevents translation in any direction in the plane. Allows rotation freely. Introduces **two unknown reaction force components** (typically Ax, Ay). Does not resist moments.

### Roller
Connects the body to a surface. Prevents translation perpendicular to the surface (normal direction). Allows translation parallel to the surface and rotation. Introduces **one unknown reaction force**, directed normal to the rolling surface.

### Fixed (Clamped) Support
Connects the body rigidly to a wall or base. Prevents all translation and all rotation. Introduces **two unknown reaction force components and one unknown reaction moment** (Ax, Ay, MA). The most constraining planar support.

### Cable (Rope, String)
A flexible, inextensible connector that can only carry tension. Transmits a **single tensile reaction force directed along the cable away from the body**. Cannot push; if equilibrium requires compression in a cable, the cable is slack (zero force) and the constraint is inactive.

### Contact (Surface Contact, Smooth Surface)
A frictionless surface or point contact. Prevents interpenetration, i.e., prevents motion into the surface. Introduces **one unknown reaction force directed normal to the contact surface**, always compressive (the surface can push but not pull the body).

---

## Applied Load Types

### Point Force
A single force applied at a specific location on the body. Characterized by magnitude (N), direction (angle or component form), and point of application. Appears directly in ΣFx = 0 and ΣFy = 0, and contributes a moment about any reference point.

### Point Moment (Applied Couple Moment)
A pure moment (torque) applied at a specific location on the body. Characterized by magnitude (N·m) and sense (clockwise or counterclockwise). Appears directly in ΣM = 0 regardless of the reference point chosen — a pure moment has the same value about every point.

### Distributed Load — Uniform
A load applied continuously along a length, with constant intensity w (N/m). The resultant is a single point force of magnitude R = w · L, acting at the **midpoint** (centroid of the rectangular load diagram) of the loaded region.

### Distributed Load — Linear (Triangular)
A load applied continuously along a length, with intensity that varies linearly from zero at one end to w₀ at the other. The resultant is a single point force of magnitude R = (1/2) · w₀ · L, acting at the **centroid of the triangular load diagram**: located at L/3 from the high-intensity end, or 2L/3 from the zero end.

---

## Moment

The tendency of a force to cause rotation about a point. Scalar definition: M = F · d⊥, where F is the force magnitude and d⊥ is the perpendicular distance from the reference point to the line of action of the force. Vector definition: **M** = **r** × **F**, where **r** is any position vector from the reference point to any point on the line of action. Units: N·m. Sign is determined by the adopted sign convention (typically counterclockwise positive).

---

## Couple

Two equal, opposite, and non-collinear forces. Their net force is zero but they produce a net moment M = F · d, where d is the perpendicular distance between the two lines of action. A couple produces a pure moment that is the same about every point — it has no net translational effect and its moment value is location-independent.

---

## Equilibrium

A rigid body is in **static equilibrium** when its acceleration is zero: both linear and angular. In 2D, this requires three scalar conditions:

```
ΣFx = 0    (sum of all x-components of external forces)
ΣFy = 0    (sum of all y-components of external forces)
ΣM_P = 0   (sum of all moments about any point P)
```

These three equations are independent and necessary. Satisfying only two does not guarantee equilibrium.

---

## Sign Convention

A set of rules assigning positive or negative values to directions and senses. For this system:

- **Positive x:** rightward
- **Positive y:** upward
- **Positive moment:** counterclockwise (CCW)

Sign convention must be declared at the start of every problem and applied consistently throughout. A negative result for an unknown means the actual direction is opposite to the assumed direction — this is valid and expected.

---

## Reference Point

The point about which moments are summed in ΣM = 0. Any point in the plane is valid. The choice does not affect whether the body is in equilibrium, but it affects algebraic complexity. The strategic choice is to select a point that lies on the line of action of one or more unknowns, eliminating those unknowns from the moment equation and simplifying the solution.

---

## Resultant

A single force (and possibly a single moment) that is statically equivalent to a system of forces and moments — it produces the same net force and the same net moment about every point. For a distributed load, the resultant is the equivalent concentrated force with magnitude equal to the area of the load diagram, applied at the centroid of that diagram.

---

## Statically Determinate

A system is statically determinate when the number of independent equilibrium equations equals the number of unknowns. In 2D:

```
Number of unknowns = 3  →  one rigid body, solved by ΣFx, ΣFy, ΣM
```

All unknown reactions can be found from equilibrium alone, without knowledge of material properties or deformations.

---

## Statically Indeterminate

A system is statically indeterminate when there are more unknowns than independent equilibrium equations. The extra unknowns are **redundant reactions**. Solving an indeterminate structure requires compatibility equations relating deformations to reactions (outside the scope of rigid body statics MVP).

The **degree of indeterminacy** = (number of unknowns) − (number of independent equilibrium equations).
