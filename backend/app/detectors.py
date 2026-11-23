"""Independent CPU detectors with explicit, bounded training-period fitting."""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.preprocessing import RobustScaler


def _utc(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("Split boundaries must be timezone-aware")
    return timestamp.tz_convert("UTC")


class BoundedTrainingSampler:
    """Uniform priority sample, reproducible across input batch sizes.

    Only O(max_rows + input batch rows) memory is needed. Input must already be
    restricted to training time; train_end additionally enforces that contract.
    """
    def __init__(self, max_rows=20000, seed=42, train_end=None):
        if max_rows < 2:
            raise ValueError("Training sample bound must be at least two")
        self.max_rows = max_rows
        self.rng = np.random.default_rng(seed)
        self.train_end = _utc(train_end) if train_end is not None else None
        self.frame = None
        self.keys = np.empty(0)
        self.seen = 0
        self.start = None
        self.end = None

    def update(self, frame):
        if frame.empty:
            return
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError("Training data must have timezone-aware timestamps")
        if not frame.index.is_monotonic_increasing or not frame.index.is_unique or frame.index.hasnans:
            raise ValueError("Training timestamps must be strictly increasing")
        if self.end is not None and frame.index[0] <= self.end:
            raise ValueError("Training batches overlap or are out of order")
        if self.train_end is not None and frame.index[-1] > self.train_end:
            raise ValueError("Training data exceeds the chronological training boundary")
        self.start = frame.index[0] if self.start is None else self.start
        self.end = frame.index[-1]
        self.seen += len(frame)
        keys = np.r_[self.keys, self.rng.random(len(frame))]
        candidate = frame if self.frame is None else pd.concat([self.frame, frame])
        if len(candidate) > self.max_rows:
            selected = np.argpartition(keys, self.max_rows - 1)[:self.max_rows]
            self.frame = candidate.iloc[selected].copy()
            self.keys = keys[selected]
        else:
            self.frame = candidate.copy()
            self.keys = keys

    def sample(self):
        return pd.DataFrame() if self.frame is None else self.frame.sort_index()

    def metadata(self):
        return {"training_rows_seen": self.seen, "training_sample_rows": 0 if self.frame is None else len(self.frame),
                "training_start": self.start.isoformat() if self.start is not None else None,
                "training_end": self.end.isoformat() if self.end is not None else None,
                "sampling": "uniform seeded priority sample of training observations"}


def _batches(frame_or_batches):
    return [frame_or_batches] if isinstance(frame_or_batches, pd.DataFrame) else frame_or_batches


def _valid(frame):
    valid = pd.Series(True, index=frame.index)
    if "value" in frame:
        valid &= np.isfinite(frame.value)
    if "feature_valid" in frame:
        valid &= frame.feature_valid.astype(bool)
    return valid


class StatisticalDetector:
    def __init__(self, threshold=6.0, quantile=None, max_train_rows=20000, seed=42):
        if not np.isfinite(threshold) or threshold < 0:
            raise ValueError("Statistical threshold must be finite and nonnegative")
        if quantile is not None and not 0 < quantile < 1:
            raise ValueError("Threshold quantile must be between zero and one")
        self.threshold = float(threshold)
        self.quantile = quantile
        self.max_train_rows = max_train_rows
        self.seed = seed
        self._training = {"status": "fixed_threshold"}

    def fit(self, training, train_end=None):
        sample = BoundedTrainingSampler(self.max_train_rows, self.seed, train_end)
        for batch in _batches(training):
            sample.update(batch.loc[_valid(batch), ["robust_score"]].dropna())
        if self.quantile is not None:
            values = sample.sample()
            if values.empty:
                raise ValueError("No valid training observations for threshold calibration")
            self.threshold = float(values.robust_score.quantile(self.quantile))
        self._training = sample.metadata()
        return self

    def score(self, features):
        scores = features.robust_score.astype(float)
        flag = _valid(features) & np.isfinite(scores) & (scores > self.threshold)
        return pd.DataFrame({"statistical_score": scores, "statistical_flag": flag}, index=features.index)

    def metadata(self):
        return {"name": "causal_median_mad", "threshold": self.threshold, "quantile": self.quantile,
                "comparison": "strictly greater than threshold", "seed": self.seed, **self._training}


class IsolationForestDetector:
    def __init__(self, contamination=.01, seed=42, max_train_rows=20000,
                 batch_size=25000, n_estimators=100, columns=None):
        if not 0 < contamination <= .5:
            raise ValueError("Contamination must be in (0, .5]")
        if batch_size < 1 or n_estimators < 1:
            raise ValueError("Batch size and estimator count must be positive")
        self.contamination = float(contamination)
        self.seed = seed
        self.max_train_rows = max_train_rows
        self.batch_size = batch_size
        self.n_estimators = n_estimators
        self.columns = columns
        self.model = None

    def fit(self, training, train_end=None):
        sampler = BoundedTrainingSampler(self.max_train_rows, self.seed, train_end)
        for frame in _batches(training):
            if self.columns is None:
                self.columns = [c for c in ("value", "value_change", "robust_score", "dispersion", "gap_ratio") if c in frame]
                if not self.columns:
                    self.columns = list(frame.select_dtypes(include="number").columns)
            sampler.update(frame.loc[_valid(frame), self.columns])
        sample = sampler.sample().replace([np.inf, -np.inf], np.nan)
        if len(sample) < 30:
            raise ValueError("Isolation Forest needs at least 30 valid training observations")
        self.fill_values = sample.median().fillna(0)
        self.scaler = RobustScaler()
        scaled = self.scaler.fit_transform(sample.fillna(self.fill_values)).astype(np.float32)
        self.model = IsolationForest(n_estimators=self.n_estimators, contamination=self.contamination,
                                     random_state=self.seed, n_jobs=2, max_samples=min(256, len(sample)))
        self.model.fit(scaled)
        self._training = sampler.metadata()
        return self

    def score(self, features):
        if self.model is None:
            raise ValueError("Fit the detector on training data before scoring")
        scores = np.full(len(features), np.nan)
        flags = np.zeros(len(features), dtype=bool)
        for start in range(0, len(features), self.batch_size):
            stop = min(start + self.batch_size, len(features))
            batch = features.iloc[start:stop]
            valid = _valid(batch).to_numpy()
            if not valid.any():
                continue
            clean = batch.loc[valid, self.columns].replace([np.inf, -np.inf], np.nan).fillna(self.fill_values)
            z = self.scaler.transform(clean).astype(np.float32)
            score = -self.model.score_samples(z)
            positions = np.flatnonzero(valid) + start
            scores[positions] = score
            flags[positions] = score > -self.model.offset_
        return pd.DataFrame({"iforest_score": scores, "iforest_flag": flags}, index=features.index)

    def metadata(self):
        return {"name": "isolation_forest", "contamination": self.contamination, "seed": self.seed,
                "max_train_rows": self.max_train_rows, "batch_size": self.batch_size,
                "n_estimators": self.n_estimators, "n_jobs": 2, "columns": self.columns,
                "threshold": float(-self.model.offset_) if self.model is not None else None,
                "sklearn_version": sklearn.__version__,
                "parameters": self.model.get_params() if self.model is not None else None,
                **getattr(self, "_training", {})}

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return str(path)

    @classmethod
    def load(cls, path):
        # Local model artifacts, like original pickle archives, must be trusted.
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError("Unexpected model artifact type")
        return model


def align_channels(channels, frequency, units, *, allow_mixed_units=False, max_rows=250000):
    """Explicit causal mean aggregation: bins [t-frequency,t) are labelled t.

    No interpolation/backfill. Only bins observed on all channels are retained.
    Mixed physical units require explicit permission and are standardized using
    training-only robust location/scale in the PCA detector.
    """
    if len(channels) < 2 or set(channels) != set(units):
        raise ValueError("PCA requires at least two named channels and an explicit unit for each")
    if any(not str(unit).strip() for unit in units.values()):
        raise ValueError("Physical unit metadata must be explicit")
    if len(set(units.values())) > 1 and not allow_mixed_units:
        raise ValueError("Mixed physical units require allow_mixed_units=True and documented standardization")
    interval = pd.Timedelta(frequency)
    if interval <= pd.Timedelta(0):
        raise ValueError("Resampling frequency must be a fixed positive duration")
    aligned = []
    for name, series in channels.items():
        if not isinstance(series.index, pd.DatetimeIndex) or series.index.tz is None:
            raise ValueError("PCA inputs require timezone-aware timestamps")
        if not series.index.is_monotonic_increasing or not series.index.is_unique:
            raise ValueError("PCA inputs must be chronological and unique")
        if series.empty or len(series) > max_rows:
            raise ValueError("Experimental PCA accepts nonempty bounded channel inputs only")
        if (series.index[-1] - series.index[0]) / interval + 2 > max_rows:
            raise ValueError("Resampling grid exceeds max_rows; narrow the period or coarsen frequency")
        aligned.append(series.resample(frequency, closed="left", label="right", origin="epoch").mean().rename(name))
    frame = pd.concat(aligned, axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) > max_rows:
        raise ValueError("Aligned PCA data exceeds max_rows")
    report = {"resample_frequency": str(interval), "aggregation": "mean", "bin": "[t-frequency,t)",
              "timestamp": "bin right edge", "fill": "none; complete bins only", "units": dict(units),
              "mixed_units": len(set(units.values())) > 1,
              "transformation": "per-channel RobustScaler fitted on training period only; dimensionless PCA inputs",
              "rows": len(frame)}
    return frame, report


class PCAReconstructionDetector:
    def __init__(self, contamination=.01, n_components=None, seed=42, max_train_rows=20000):
        if not 0 < contamination <= .5:
            raise ValueError("Contamination must be in (0, .5]")
        self.contamination = contamination
        self.n_components = n_components
        self.seed = seed
        self.max_train_rows = max_train_rows

    def fit(self, training, *, alignment, train_end=None):
        if not alignment or "resample_frequency" not in alignment:
            raise ValueError("PCA requires documented explicit temporal alignment")
        sample = BoundedTrainingSampler(self.max_train_rows, self.seed, train_end)
        for frame in _batches(training):
            sample.update(frame.replace([np.inf, -np.inf], np.nan).dropna())
        x = sample.sample()
        if len(x) < 30 or x.shape[1] < 2:
            raise ValueError("PCA needs at least 30 training rows and two aligned channels")
        self.columns = list(x.columns)
        self.scaler = RobustScaler()
        z = self.scaler.fit_transform(x)
        components = self.n_components if self.n_components is not None else x.shape[1] - 1
        if not 1 <= components < x.shape[1]:
            raise ValueError("PCA components must be fewer than input channels")
        self.model = PCA(n_components=components, random_state=self.seed).fit(z)
        errors = np.mean((z - self.model.inverse_transform(self.model.transform(z))) ** 2, axis=1)
        self.threshold = float(np.quantile(errors, 1 - self.contamination))
        self.alignment = dict(alignment)
        self._training = sample.metadata()
        return self

    def score(self, frame, batch_size=25000):
        if not hasattr(self, "model"):
            raise ValueError("Fit PCA on aligned training rows before scoring")
        errors = np.full(len(frame), np.nan)
        for lo in range(0, len(frame), batch_size):
            batch = frame.iloc[lo:lo + batch_size][self.columns]
            valid = np.isfinite(batch).all(axis=1)
            if not valid.any():
                continue
            z = self.scaler.transform(batch.loc[valid])
            errors[lo + np.flatnonzero(valid)] = np.mean((z - self.model.inverse_transform(self.model.transform(z))) ** 2, axis=1)
        return pd.DataFrame({"pca_error": errors, "pca_flag": errors > self.threshold}, index=frame.index)

    def metadata(self):
        return {"name": "experimental_pca", "alignment": self.alignment, "threshold": self.threshold,
                "n_components": self.model.n_components_, "seed": self.seed, "contamination": self.contamination,
                **self._training}


def fit_random_forest(training, labels, *, unlabelled_policy="exclude", labelled_channel=True,
                      seed=42, max_train_rows=20000, train_end=None):
    """Train on explicit 0/1 labels; unknowns stay unknown unless opted in.

    Target=NO is never a source of negative labels. Even with assume_normal,
    an unlabelled channel is skipped. Caller supplies training-period rows only.
    """
    if unlabelled_policy not in {"exclude", "assume_normal"}:
        raise ValueError("unlabelled_policy must be exclude or assume_normal")
    if not labelled_channel:
        return None, {"status": "skipped", "reason": "Channel has no eligible ground truth; Target=NO is not negative evidence"}
    target = labels.reindex(training.index)
    observed = target.dropna()
    if not observed.isin([0, 1]).all():
        raise ValueError("Supervised labels must be 0, 1 or unknown (NaN)")
    unknown = int(target.isna().sum())
    if unlabelled_policy == "assume_normal":
        target = target.fillna(0)
    data = training.replace([np.inf, -np.inf], np.nan).copy()
    data["__target"] = target
    data = data.dropna()
    sampler = BoundedTrainingSampler(max_train_rows, seed, train_end)
    sampler.update(data)
    sample = sampler.sample()
    info = {"unlabelled_policy": unlabelled_policy, "assumed_normal_rows": unknown if unlabelled_policy == "assume_normal" else 0,
            "excluded_unknown_rows": unknown if unlabelled_policy == "exclude" else 0, "seed": seed, **sampler.metadata()}
    if len(sample) < 50 or sample.__target.nunique() < 2:
        return None, {**info, "status": "skipped", "reason": "Insufficient labelled training rows or missing positive/negative class"}
    model = RandomForestClassifier(n_estimators=150, class_weight="balanced_subsample",
                                   min_samples_leaf=3, random_state=seed, n_jobs=2)
    model.fit(sample.drop(columns="__target"), sample.__target.astype(int))
    return model, {**info, "status": "trained", "name": "random_forest", "parameters": model.get_params()}
