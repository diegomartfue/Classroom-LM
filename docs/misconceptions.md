# Known Student Misconceptions in 2D Rigid Body Statics

This catalog is used by the Student Modeler agent to detect, track, and address common errors. Each entry includes an ID, description, observable symptoms in student work, and a remediation strategy.

---

## FBD Construction

**FBD-01**
- **Description:** Omitting reaction forces at supports
- **What it looks like:** Student draws the body with applied loads but leaves out one or more support reactions (e.g., forgets the horizontal reaction at a pin, or omits the moment reaction at a fixed support).
- **How to address:** Ask the student to identify each support type and list the degrees of freedom it removes. Walk through what motion each reaction prevents.

**FBD-02**
- **Description:** Including internal forces on the FBD
- **What it looks like:** Student draws forces between parts of the same rigid body, or includes the weight of a removed support as an external force on the body.
- **How to address:** Clarify that an FBD shows only forces external to the body being analyzed. Internal forces cancel in pairs and disappear when the body is treated as a single system.

**FBD-03**
- **Description:** Wrong direction for reaction forces
- **What it looks like:** Student draws a roller reaction tangent to the surface instead of normal, or reverses the direction of a pin reaction without justification.
- **How to address:** Reinforce that a roller can only push (compress), never pull. For pins, the direction is unknown; show that assuming a direction and getting a negative result is valid — it just means the force acts the other way.

**FBD-04**
- **Description:** Treating a cable as capable of pushing
- **What it looks like:** Student draws a compressive force along a cable, or does not constrain the cable reaction to be tensile.
- **How to address:** Emphasize that cables are flexible and can only pull. If equilibrium requires compression in a cable, the problem setup must be re-examined.

**FBD-05**
- **Description:** Forgetting the body's own weight
- **What it looks like:** Student correctly draws all support reactions and external loads but omits the distributed gravitational load (or its resultant at the centroid).
- **How to address:** Prompt: "Is the body massless? If not, where does gravity act?"

---

## Equilibrium Equations

**EQ-01**
- **Description:** Using only two scalar equations for a planar problem
- **What it looks like:** Student writes ΣFx = 0 and ΣFy = 0 but never writes ΣM = 0, leaving one equation and one unknown unused (or over-constraining by guessing).
- **How to address:** State that planar equilibrium always yields three independent equations. The moment equation is not optional.

**EQ-02**
- **Description:** Applying ΣF = 0 to find moments, or vice versa
- **What it looks like:** Student sums forces about a point, or computes "ΣM = Force × Force."
- **How to address:** Distinguish clearly: ΣF = 0 relates force components; ΣM = 0 relates moments (force × perpendicular distance). These are separate equations with different physical meanings.

**EQ-03**
- **Description:** Sign errors when resolving force components
- **What it looks like:** A force at an angle has its x- and y-components swapped, or a component pointing left is entered as positive.
- **How to address:** Establish a sign convention at the start of every problem. Draw the positive axes. Check each component against the diagram before writing the equation.

**EQ-04**
- **Description:** Double-counting a force in both ΣFx and ΣM without accounting for it correctly
- **What it looks like:** Student adds the full magnitude of a force to the moment sum even though only the perpendicular component contributes, or adds both components when one is parallel to the moment arm.
- **How to address:** Review the definition of moment: M = F × d_perp, or equivalently use the cross product. Only the component perpendicular to the position vector creates a moment.

**EQ-05**
- **Description:** Forgetting to include all forces in a summation
- **What it looks like:** ΣFy equation is missing one vertical reaction, giving an incorrect result that happens to satisfy the equation.
- **How to address:** Before writing equations, list every force on the FBD and check each one appears in at least one equation.

---

## Reference Point Selection

**RP-01**
- **Description:** Taking moments about a non-convenient point, creating unnecessary algebra
- **What it looks like:** Student sums moments about the origin or a random point when summing about an unknown's line of action would eliminate that unknown immediately.
- **How to address:** Teach the strategy: choose the moment center to be the intersection of as many unknown force lines of action as possible. This minimizes simultaneous equations.

**RP-02**
- **Description:** Using the wrong perpendicular distance in the moment calculation
- **What it looks like:** Student uses the straight-line distance from the reference point to the point of application instead of the perpendicular distance from the reference point to the line of action.
- **How to address:** Draw the line of action extended. Drop a perpendicular from the reference point to that line. That length is d_perp.

**RP-03**
- **Description:** Believing that ΣM = 0 depends on which point is chosen
- **What it looks like:** Student expresses confusion that different reference points give "different answers" and picks one arbitrarily.
- **How to address:** Show that for a body in equilibrium, ΣM = 0 holds about any point. Different choices produce different equations that are all consistent — they are not independent if the body is already in equilibrium from the force equations.

---

## Distributed Loads

**DL-01**
- **Description:** Placing the resultant of a uniform distributed load at the end of the loaded region instead of its midpoint
- **What it looks like:** For a UDL of length L, student places the resultant force at x = 0 or x = L rather than x = L/2.
- **How to address:** The resultant of a uniform load acts at the centroid of the load diagram (a rectangle). The centroid of a rectangle is at its midpoint.

**DL-02**
- **Description:** Placing the resultant of a triangular distributed load at the midpoint instead of the third-point
- **What it looks like:** For a linearly varying load that goes from zero to w₀ over length L, student places the resultant at L/2 instead of 2L/3 from the zero end (or L/3 from the peak end).
- **How to address:** The load diagram is a triangle. The centroid of a triangle is at 1/3 of its base from the larger end, or 2/3 from the smaller end.

**DL-03**
- **Description:** Using the peak intensity w₀ as the resultant magnitude instead of the area of the load diagram
- **What it looks like:** Student writes R = w₀ instead of R = (1/2) w₀ L for a triangular load, or R = w₀ instead of R = w₀ L for a uniform load.
- **How to address:** The resultant magnitude equals the area of the load intensity diagram. Units confirm this: (N/m) × (m) = N.

**DL-04**
- **Description:** Forgetting to convert a distributed load to its resultant before writing equilibrium equations
- **What it looks like:** Student writes w(x) directly into ΣFy with no integration or area computation.
- **How to address:** For rigid body equilibrium (as opposed to internal force analysis), always replace distributed loads with their statically equivalent resultant force first.

---

## Conceptual

**CON-01**
- **Description:** Confusing a moment (torque) with a force
- **What it looks like:** Student adds a moment directly to a force sum, or resolves an applied couple into force components.
- **How to address:** Forces and moments are distinct quantities with different units (N vs N·m). They appear in separate equilibrium equations and cannot be added together.

**CON-02**
- **Description:** Believing that a body with more supports than unknowns is always over-constrained (indeterminate)
- **What it looks like:** Student incorrectly labels a problem statically indeterminate when the extra reactions are actually redundant geometric constraints that can still be resolved.
- **How to address:** Introduce the condition: a problem is statically determinate when the number of unknowns equals the number of independent equilibrium equations. Count carefully before concluding indeterminacy.

**CON-03**
- **Description:** Thinking equilibrium means the body is stationary
- **What it looks like:** Student states that a moving object cannot be in equilibrium.
- **How to address:** Equilibrium requires ΣF = 0 and ΣM = 0, which means zero acceleration, not zero velocity. A body moving at constant velocity in a straight line is in equilibrium.

**CON-04**
- **Description:** Assuming that symmetric geometry implies symmetric reactions
- **What it looks like:** For a symmetrically loaded beam on two supports, student assumes both reactions are equal without checking; then applies this assumption to asymmetric loading cases.
- **How to address:** Symmetry is a valid shortcut only when both geometry and loading are symmetric about the same axis. Verify before applying.

**CON-05**
- **Description:** Misidentifying the type of support and therefore the number of unknowns it introduces
- **What it looks like:** Student models a fixed support as a pin (losing the moment reaction) or a roller as a pin (adding a spurious horizontal reaction).
- **How to address:** Review each support type: pin (2 unknown force components), roller (1 unknown normal force), fixed wall (2 force components + 1 moment), cable (1 tensile force along cable axis), contact (1 normal force, direction known from geometry).
