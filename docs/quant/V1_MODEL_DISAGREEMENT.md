# Model Disagreement as a Research Primitive

Christiania does not seek a single magical 'true price'. V1 treats disagreement between reasonable models as a diagnostic object.

A model-disagreement record can describe the model mean, median, standard deviation, median absolute deviation, absolute range, relative range and—when a market price is supplied—the market-minus-model-mean and market-minus-model-median residuals. It also identifies the model furthest from the cross-model median without imposing an arbitrary outlier threshold.

The models are heterogeneous deterministic pricing systems with different structural assumptions. Their cross-model standard deviation is therefore a **descriptive dispersion scale only**. A market distance expressed in model-standard-deviation units is **not a statistical z-score**, p-value, confidence measure, sampling uncertainty estimate, or probability. Christiania exposes `statistical_inference_valid = false` with this diagnostic contract.

These values are **not trade signals**. Large disagreement can arise from poor calibration, sparse strikes, event risk, unstable local-vol inversion, jump assumptions, wide markets or model misspecification. A single structurally different stress model can also widen the ensemble dispersion while the benchmark models remain tightly clustered; that situation should be investigated as model disagreement rather than summarized away as statistical insignificance. Future prospective research may test whether disagreement contains stable information, but V1 does not grant it decision authority.
