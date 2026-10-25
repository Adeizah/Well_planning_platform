# Hard KOP azimuth update

The independent optimizer now carries a constant azimuth placeholder before the declared KOP and maps azimuth steering controls over the post-KOP interval. The independent validator checks that the stored azimuth placeholder remains constant before KOP, alongside the existing zero-inclination and zero-lateral-departure checks.

Azimuth is geometrically undefined at zero inclination; the constant pre-KOP value is a stable survey representation, not a physical steering direction. This does not replace DLS validation, and all post-KOP trajectory changes remain subject to the DLS limit.

Validation performed for this update: Python compilation passed. The combined existing validation/general-optimizer pytest run did not complete within the available time and reported failures before timeout; full regression status is therefore unverified and requires investigation before operational reliance.
