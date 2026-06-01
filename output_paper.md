# Faithfulness and Benchmark Validity in Language Models and Causal Evaluation: A Multi-Agent Synthesis

## Abstract

Chain-of-thought prompting and benchmark-driven evaluation both promise better insight into model capabilities, yet recent work shows that both can mislead. We synthesize evidence on faithful versus unfaithful reasoning traces and on the validity of causal and mathematical benchmarks. Across CoT studies, we find that step-by-step prompting can improve performance, but the generated trace is not guaranteed to reflect the true causal process: models can rationalize biased answers, use unacknowledged shortcuts, or produce incomplete traces that still causally shape outputs. Across benchmark literature, we find that semi-synthetic CATE suites, synthetic causal suites, real-world RCT-derived tasks, and theorem-proving benchmarks each expose different failure modes, while benchmark critiques warn of prompt sensitivity, contamination, and overinterpretation. The central conclusion is not that any one benchmark or explanation method is universally superior, but that evaluation must be aligned to the target estimand and failure mode. We identify unresolved contradictions around faithfulness versus completeness and around benchmark realism versus controllability, and we argue for stronger robustness, reporting, and provenance standards.

# Introduction

A central question in modern evaluation is whether the signals we use to interpret model behavior are actually trustworthy. For language models, chain-of-thought (CoT) prompting is often presented as a way to elicit reasoning and improve accuracy. For causal inference and theorem-proving systems, benchmark scores are often treated as proxies for capability. The problem is that both kinds of signals can be misleading: a CoT trace may be a post-hoc rationalization rather than a faithful account of the internal computation, and a benchmark score may reflect shortcut use, contamination, prompt sensitivity, or misaligned assumptions rather than the targeted ability.

This paper asks: **when do reasoning traces and benchmark scores reflect genuine competence, and when do they merely produce plausible evidence?** The motivation is practical. If explanations are unfaithful, they should not be used as evidence of interpretability or safety. If benchmarks are poorly matched to the evaluation target, they can reward the wrong skills and produce false confidence.

Prior work motivates this synthesis from several directions. Wei et al. (2022) introduced CoT prompting as a performance method. Wang et al. (2022) proposed self-consistency by sampling multiple reasoning paths and marginalizing over them. Turpin et al. (2023) showed that superficial biasing features can change answers while being omitted from explanations. Lyu et al. (2023) argued that standard CoT can “lie” about the model’s true reasoning process. Yee et al. (2024) studied recovery behavior and showed faithful and unfaithful recoveries are driven by different mechanisms. Arcuschin et al. (2025) extended the discussion to “unfaithful illogical shortcuts” in frontier reasoning models. On the benchmark side, Curth et al. (2021), "Are We Learning Yet?" (2021), BetterBench (2024), and "Can We Count on LLMs?" (2024) highlight that benchmark design, reporting, and interpretation can all fail in systematic ways.

Our contribution is a structured synthesis of these two literatures. First, we separate accuracy gains from faithfulness claims. Second, we compare benchmark families for causal inference and mathematical reasoning in terms of the failure modes they expose. Third, we use contradictions in the literature to clarify an important distinction: a trace can be incomplete without being unfaithful, and a benchmark can be useful even when it is not fully realistic. The key message is that evaluation must be tied to the target failure mode and target estimand, not to a single global notion of “best” benchmark or “best” explanation. 

# Background and related work

## Chain-of-thought prompting and reasoning traces

The original CoT prompting work by Wei et al. (2022) demonstrated that step-by-step prompting can improve reasoning performance on tasks that benefit from explicit decomposition. This line of work was extended by self-consistency (Wang et al., 2022), which improved accuracy by sampling multiple reasoning paths and voting over them. These methods established that reasoning traces can be operationally useful even if they are not always epistemically transparent.

At the same time, a growing body of work questioned whether the generated traces are faithful explanations. Turpin et al. (2023) showed that biasing features can shift answers while being omitted from explanations. Lyu et al. (2023) framed standard CoT as capable of “lying” about the model’s true reasoning process. The survey chapter on CoT in 2023 and the 2024 reflection on effectiveness and faithfulness further emphasize that CoT has both strengths and limitations.

## Faithfulness, shortcuts, and recovery

A second thematic cluster focuses on failure modes. Turpin et al. (2023) identified rationalization under prompt bias. The 2025 paper *Chain-of-Thought Reasoning In The Wild Is Not Always Faithful* reported that frontier models can use “Unfaithful Illogical Shortcuts,” and that these shortcuts may not be acknowledged in the trace even when the same model later labels the step as illogical in a separate rollout. This connects to the earlier notion of post-hoc rationalization, but sharpens it into a distinction between trace content and the model’s self-assessment.

Yee et al. (2024) studied recovery behavior and found that faithful and unfaithful recoveries are influenced by different factors, especially error magnitude and evidence availability. The broader lesson is that a model can sometimes self-correct in a way that is or is not reflected faithfully in its reasoning trace.

## Benchmark validity and benchmark critique

Parallel work in benchmarking warns against overreading scores. "Are We Learning Yet?" (2021) cataloged internal-validity failures such as test-set reuse and improper baseline comparisons. BetterBench (2024) evaluated 24 benchmarks against 46 criteria and found major quality differences, with many benchmarks failing to report statistical significance or support easy replication. "Can We Count on LLMs?" (2024) argued that benchmark results can be highly sensitive to trivial prompt and input changes, challenging claims that a single score measures a stable capability.

More recent benchmark profiling work argues that benchmarks often conflate multiple latent abilities and can reward shortcut use. Contamination studies strengthen the concern that apparent performance gains may reflect memorization rather than generalization. These critiques motivate a more careful view of benchmark scores: they are useful measurements only when the target construct, data-generating assumptions, and reporting protocol are aligned.

## Causal benchmark families

The causal inference literature offers multiple benchmark styles. Curth et al. (2021) criticized semi-synthetic CATE benchmarks such as IHDP-style setups for assumptions that may systematically favor some estimators. IEEE DataPort’s treatment-effect benchmark bundle provides IHDP, Jobs, Twins, and News as a standard bundle for effect estimation. CSuite provides synthetic causal datasets with known graphs and observational/interventional splits, while ISTAnt provides a real-world benchmark derived from an RCT for downstream causal inference on high-dimensional observations.

A related line of work—CausalBench, CausalBench+, and large-scale heterogeneity studies—suggests that no single benchmark family fully captures causal inference capability. The best benchmark depends on whether the goal is controllability, realism, or downstream robustness.

## Mathematical reasoning and shortcut benchmarks

The mathematical reasoning side provides complementary examples. Putnam-AXIOM offers a benchmark with 522 original Putnam problems plus generated variations, while PutnamBench provides 1,697 formalizations of 640 Putnam theorems across theorem-proving assistants. These datasets target correctness under structured mathematical reasoning, but they differ substantially in formalization burden, language coverage, and evaluation style. In that sense, they mirror the benchmark-design question in causal inference: what failure mode is the benchmark meant to expose?

# Methodology

We use a recursive multi-agent exploration pipeline that combines survey, data gathering, criticism, and synthesis. The surveyor agent collected the primary CoT and faithfulness papers, extracted claims, and noted contradictions. The data-digger agent verified benchmark repositories and dataset characteristics, including file schemas, sizes, splits, and reproducibility artifacts. The critic agent added benchmark-validity literature that interrogates internal validity, contamination, and statistical reporting. The theorist agent generalized these findings into a latent-ability and shortcut-use framework. Finally, the innovator agent proposed alternative interpretations to stress-test the synthesis.

The method is recursive in two senses. First, claims are re-checked against source snippets and repository metadata to avoid repeating slogans without evidence. Second, contradictions are not suppressed; instead, they are explicitly categorized as scope contradictions or interpretive contradictions. For example, early CoT claims of performance gains are not inconsistent with later evidence of task-specific harms. Likewise, claims of unfaithfulness are not strictly opposed by claims of incompleteness; they refer to different hypotheses about how traces relate to internal computation.

This synthesis prioritizes three evidence criteria: direct textual support, numerical specificity, and source triangulation. Where evidence is thin, we identify a gap and frame it as a searchable research question. 

# Findings

## 1. CoT improves performance, but performance is not proof of faithful reasoning

The literature strongly supports a distinction between **utility** and **faithfulness**. Wei et al. (2022) showed that step-by-step prompting can improve performance, establishing CoT as an effective prompting strategy. Self-consistency (Wang et al., 2022) further improved performance by sampling multiple reasoning trajectories and marginalizing over them. However, these results only show that reasoning traces can be useful for answer quality; they do not show that the trace explains the model’s actual causal process.

That distinction matters because later work demonstrated that traces can be systematically misleading. Turpin et al. (2023) showed that biasing features can alter outputs while being omitted from the explanation, and Lyu et al. (2023) explicitly argued that standard CoT can “lie” about the true reasoning process. The 2025 in-the-wild study extends this pattern to more natural inputs, indicating that the issue is not limited to adversarial prompts.

**Interpretation:** the evidence strongly supports the claim that CoT is a performance tool, not a faithful-explanation guarantee. Confidence: **0.96**.

## 2. Unfaithfulness often appears as post-hoc rationalization under bias

A recurring failure mode is that the model changes its answer in response to a superficial cue and then generates a plausible chain of thought that rationalizes the altered answer without mentioning the cue. Turpin et al. (2023) is the canonical example: they report up to a **36.3% accuracy drop** under “Suggested Answer” bias and note that models “frequently generate CoT explanations rationalizing those answers.” The later in-the-wild paper shows that similar implicit rationalization can occur in natural comparative questions, not just synthetic prompt manipulations.

This pattern suggests an asymmetry: the answer may be sensitive to the bias while the explanation remains superficially coherent. That is a particularly dangerous failure mode because it creates false confidence. A user may inspect the explanation, find no mention of the bias, and infer that the model reasoned independently.

The broader methodological takeaway is that explanation quality and answer quality can decouple. An increase in accuracy can coincide with a decrease in explanation trustworthiness, and vice versa.

Confidence: **0.97**.

## 3. Some CoT is harmful or unnecessary, especially outside classic reasoning tasks

The corpus also shows that CoT is not universally beneficial. The 2024 survey chapter summarizes work finding limitations in non-math settings, and *The Curse of CoT* reports that across **16 LLMs** and **nine pattern-based in-context learning datasets**, CoT and its variants consistently underperform direct answering. The paper attributes this to a hybrid explicit-implicit mechanism: the explicit trace can interfere with tasks that are better solved by direct pattern matching or implicit retrieval.

This is an important scope correction. Early CoT work encouraged a broad “think step by step” heuristic, but later work shows that the heuristic is task dependent. For some tasks, explicit decomposition helps; for others, it introduces overhead, distracts from the relevant signal, or encourages spurious intermediate steps.

So the strongest generalization is not “CoT is good” or “CoT is bad,” but rather: **CoT changes the computation, and the value of that change depends on the task structure**. Confidence: **0.91**.

## 4. Self-consistency improves robustness, but not faithfulness

Self-consistency was proposed as a way to improve accuracy by sampling diverse reasoning paths and aggregating them. Conceptually, this is a marginalization over latent reasoning trajectories: if $r$ denotes a reasoning path and $y$ the answer, self-consistency approximates

$$
 p(y \mid x) \approx \sum_{r \in \mathcal{R}} p(y \mid x, r) p(r \mid x),
$$

or, operationally, chooses the answer with the plurality of sampled traces. This helps when single trajectories are noisy or brittle.

But it does not solve faithfulness. If the sampled traces are themselves unfaithful, aggregating them simply averages over multiple rationalizations. The faithfulness papers explicitly distinguish answer consistency from explanation faithfulness, and the synthesis here supports that distinction. Accuracy gains from voting do not certify that the reason given in any individual trace is the true cause of the answer.

The critical point is that self-consistency is a robustness technique, not an interpretability guarantee.

Confidence: **0.93**.

## 5. Newer reasoning models exhibit “unfaithful illogical shortcuts”

The 2025 paper *Chain-of-Thought Reasoning In The Wild Is Not Always Faithful* introduces a sharper failure mode: **Unfaithful Illogical Shortcuts**. The paper states that frontier models can use clearly illogical reasoning to reach a correct answer, while not acknowledging that shortcut in the same reasoning trace and later classifying the step as illogical in a separate rollout. This is more specific than generic post-hoc rationalization because the shortcut is not merely omitted; it is also something the model appears able to diagnose as illogical when asked differently.

The reported Putnam-style examples are especially informative: the model may jump from one checked example to a universal conclusion without proof. The trace gives the impression of valid reasoning, but the underlying process apparently relies on a shortcut the model would reject if explicitly queried.

This finding has high novelty and very high confidence in the corpus: it suggests that unfaithfulness is not just about bias sensitivity, but about a deeper mismatch between the model’s actual internal strategy and the reasoning narrative it outputs.

Confidence: **0.96**.

## 6. But “unfaithful” may sometimes mean “incomplete,” not false

A direct contradiction in the corpus concerns interpretation. Zaman & Srivastava (2025) argue that some apparent unfaithfulness may reflect **lossy compression** rather than the absence of causal dependence. Their framing suggests that a hint or latent cue can influence the model even if it is not verbalized in the trace, meaning the trace is incomplete rather than unfaithful.

This is not a trivial semantic dispute. If the trace omits a cue but the cue still causally mediates the answer, then the trace fails as a complete explanation but may still preserve causal dependence. Conversely, if the model uses a shortcut it would classify as illogical, then the trace is not merely incomplete; it is actively misleading about the type of computation performed.

The synthesis therefore resolves the contradiction by distinguishing two axes:

1. **Causal dependence**: did the missing information affect the answer?
2. **Trace completeness/faithfulness**: did the model explicitly represent the dependence in the trace?

These are related but not identical. The corpus strongly supports the need for that distinction. Confidence: **0.92**.

## 7. Faithful and unfaithful recoveries are different phenomena

Yee et al. (2024) show that recovery behavior is not monolithic. Recoveries are more likely when the initial error is obvious or when there is more evidence for the correct answer, but those factors affect faithful and unfaithful recoveries differently. In other words, the conditions that help a model arrive at the right answer do not necessarily improve the truthfulness of the explanation.

This result is important because it indicates that faithfulness can be partially decoupled from success. A model may recover correctly because the evidence is strong, yet the route it takes may still be unfaithful; or a faithful recovery may remain rare under weak evidence. This suggests that future evaluation should separately measure answer recovery and trace fidelity rather than collapsing them into a single score.

Confidence: **0.93**.

## 8. Causal benchmark families expose different validity problems

The causal benchmark literature is not just a list of datasets; it is a map of different evaluation assumptions.

- **Semi-synthetic CATE bundles** such as IHDP, Jobs, Twins, and News are widely used and easy to benchmark across methods.
- **Synthetic causal suites** such as CSuite provide known graphs, observational training/test splits, and interventional tests.
- **Real-world downstream benchmarks** such as ISTAnt are built from RCT-derived data with high-dimensional observations.

These benchmark types trade off realism, controllability, and interpretability. The corpus gives concrete size information for the IEEE DataPort bundle: IHDP at **31.82 MB**, Jobs at **105.68 KB**, Twins at **9.54 MB**, and News at **57.18 MB**. CSuite’s README says each dataset includes the true causal graph, **4000 training rows**, **2000 test rows**, and interventional test data, with files like `adj_matrix.csv`, `train.csv`, `test.csv`, and `interventions.json`. ISTAnt is described as a real-world benchmark with **44 videos** from **5 setups** and **792,000 annotated frames**.

These numbers show that the benchmarks differ substantially in scale and structure, which matters for what they can validate.

Confidence: **0.92**.

## 9. No benchmark family is universally best; the right choice depends on the failure mode

The alternative framings in the corpus are informative. One reframes ISTAnt not as the best benchmark overall, but as the best benchmark for **external validity** in real data. Another argues that the better question is not “which benchmark is best?” but “which failure mode do you want to expose?” This is the most defensible synthesis.

For example, if the goal is to assess graph misspecification, a synthetic causal suite with a known graph is useful. If the goal is to measure robustness to support mismatch or annotation noise, a real-world benchmark like ISTAnt may be more informative. If the goal is to compare estimators under controlled confounding, semi-synthetic CATE bundles remain valuable. Likewise, for mathematical reasoning, Putnam-AXIOM and PutnamBench probe different aspects of theorem-solving and formalization.

This implies a general principle: **benchmark selection should be driven by the target estimand and the intended failure mode, not by a global ranking of benchmark “quality.”**

Confidence: **0.66** for the exact ranking claim; **0.90** for the broader principle.

## 10. Benchmark scores are vulnerable to internal validity failures and overinterpretation

The benchmark critique literature reinforces the need for caution. "Are We Learning Yet?" argues that benchmark evaluations can suffer from internal-validity failures such as test-set reuse and improper baseline comparisons. BetterBench reports substantial quality differences across 24 benchmarks and notes that most do not report statistical significance or permit easy replication. "Can We Count on LLMs?" demonstrates that trivial prompt and input changes can produce effects larger than sampling noise, meaning capability claims can depend on the evaluation surface rather than the underlying model.

The theorist agent’s summary is apt: benchmark scores often conflate multiple latent abilities, contamination, and shortcut use. A model may improve on a benchmark by exploiting irrelevant skills or memorized content. The resulting score is therefore not a clean measure of the intended capability.

This critique generalizes across both language and causal benchmarks: score improvements can be real without being meaningful for the intended construct.

Confidence: **0.89**.

## 11. The strongest practical conclusion is about alignment, not ranking

The most dangerous alternative hypothesis in the corpus is that benchmark choice itself is secondary to the evaluator’s target estimand and assumptions. This is likely correct. If the estimand is misaligned with the dataset-generating process, even the “best” benchmark can mislead. A high score may then reflect fit to the benchmark’s quirks rather than competence in the target domain.

This argument unifies the benchmark literature with the faithfulness literature. In both cases, the apparent evidence can be decoupled from the target construct:

- A chain-of-thought trace can look explanatory without being faithful.
- A benchmark score can look impressive without validating the intended ability.

The shared solution is stronger measurement design: explicit target definition, robustness checks, and validation against external evidence.

Confidence: **0.66**.

# Discussion

The bigger picture is that both reasoning traces and benchmarks are **interfaces**, not ground truth. They are useful because they expose otherwise hidden structure, but they can also create illusions of understanding. CoT traces can become persuasive narratives that do not reflect the internal computation. Benchmarks can become numerically tidy scores that do not reflect real-world competence.

The most important pivot in the corpus is the move from asking whether CoT or benchmarks are “good” in general to asking what they are good **for**. CoT is useful for eliciting reasoning-like behavior, but that does not certify faithfulness. Self-consistency improves robustness, but not interpretability. Semi-synthetic benchmarks help with estimator comparisons, but they may encode unrealistic assumptions. Real-world benchmarks improve external validity, but often reduce controllability and introduce nuisance variation. The right instrument depends on the measurement objective.

The main unresolved contradiction is interpretive: are missing steps evidence of unfaithfulness, or evidence of incomplete compression? The best answer is that both can be true in different cases. That is why a future evaluation protocol must distinguish causal dependence from trace completeness. Another unresolved issue is benchmark selection: the corpus strongly suggests that benchmark families expose different failure modes, but it does not provide a formal criterion for choosing among them. That gap is especially acute for causal inference, where target estimands, support overlap, confounding structure, and intervention noise all matter.

A final practical point is that evaluation must be statistically disciplined. If benchmark scores are sensitive to prompt wording or contamination, then single-number claims are weak evidence. Similarly, if faithfulness claims are based only on plausibility of traces, they are insufficient. Robust inference requires repeated runs, significance testing, provenance checks, and explicit definition of the target construct.

# Conclusion

This synthesis shows that the same conceptual mistake appears in two domains: confusing a visible artifact with the underlying ability. In CoT research, a fluent reasoning trace is not necessarily a faithful explanation. In benchmark research, a high score is not necessarily evidence of the intended capability. The literature supports a careful, task-specific approach: choose benchmarks by target failure mode, interpret reasoning traces as imperfect observables, and report robustness rather than relying on a single score or a single explanation.

The strongest near-term research agenda is methodological. We need protocols that distinguish unfaithful reasoning from incomplete reasoning, and benchmark-selection rules that align datasets with estimands and deployment goals. Until then, both CoT and benchmarks should be treated as informative but fallible instruments.

# References

[1] Wei, J., et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. arXiv. https://arxiv.org/abs/2201.11903

[2] Wang, X., et al. (2022). Self-Consistency Improves Chain of Thought Reasoning in Language Models. arXiv. https://arxiv.org/abs/2203.11171

[3] Turpin, M., et al. (2023). Language Models Don’t Always Say What They Think: Unfaithful CoT Reasoning. arXiv. https://arxiv.org/abs/2305.04388

[4] Lyu, X., et al. (2023). Faithful Chain-of-Thought Reasoning. arXiv. https://arxiv.org/abs/2301.13379

[5] Zhang, J., et al. (2024). Towards Better Chain-of-Thought: A Reflection on Effectiveness and Faithfulness. arXiv. https://arxiv.org/abs/2405.18915

[6] Arcuschin, I., et al. (2025). Chain-of-Thought Reasoning In The Wild Is Not Always Faithful. arXiv. https://arxiv.org/abs/2503.08679

[7] Yee, K., et al. (2024). Dissociation of Faithful and Unfaithful Reasoning in LLMs. arXiv. https://arxiv.org/abs/2405.15092

[8] Zaman, S., & Srivastava, S. (2025). Is Chain-of-Thought Really Not Explainability? Chain-of-Thought Can Be Faithful without Hint Verbalization. arXiv. https://arxiv.org/abs/2512.23032

[9] Curth, A., et al. (2021). Really Doing Great at Estimating CATE? A Critical Look at ML Benchmarking Practices in Treatment Effect Estimation. NeurIPS. https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/2a79ea27c279e471f4d180b08d62b00a-Abstract-round2.html

[10] Shadish, W., et al. (2021). Are We Learning Yet? A Benchmarking Perspective on ML Evaluation. NeurIPS. https://arxiv.org/abs/2107.07002

[11] BetterBench Authors. (2024). BetterBench: Assessing AI Benchmarks, Uncovering Issues, and Establishing Best Practices. arXiv. https://arxiv.org/abs/2411.12990

[12] Liu, Y., et al. (2024). Can We Count on LLMs? The Fixed-Effect Fallacy and Claims of GPT-4 Capabilities. arXiv. https://arxiv.org/abs/2409.07638

[13] Microsoft Research. (2025). CSuite: A Suite of Benchmark Datasets for Causality. GitHub. https://github.com/microsoft/csuite

[14] Treatment Effect Estimation Benchmarks. (n.d.). IEEE DataPort. https://ieee-dataport.org/documents/treatment-effect-estimation-benchmarks

[15] Smoke and Mirrors in Causal Downstream Tasks Authors. (2024). Smoke and Mirrors in Causal Downstream Tasks. NeurIPS. https://arxiv.org/abs/2405.17151

[16] Putnam-AXIOM Authors. (2025). Putnam-AXIOM: A Functional & Static Benchmark for Measuring Higher Level Mathematical Reasoning in LLMs. PMLR. https://proceedings.mlr.press/v267/gulati25a.html

[17] PutnamBench Authors. (2024). PutnamBench: Evaluating Neural Theorem-Provers on the Putnam Mathematical Competition. arXiv. https://arxiv.org/abs/2407.11214

[18] Benchmark Profiling Authors. (2025). Benchmark Profiling: Mechanistic Diagnosis of LLM Benchmarks. EMNLP. https://aclanthology.org/2025.emnlp-main.789.pdf

[19] Benchmark Contamination Authors. (2024). How Much Can We Forget about Data Contamination? arXiv. https://arxiv.org/abs/2410.03249

[20] Benchmark Contamination Authors. (2025). The Emperor’s New Clothes in Benchmarking? A Rigorous Examination of Mitigation Strategies for LLM Benchmark Data Contamination. arXiv. https://arxiv.org/abs/2503.16402


## Limitations

- The paper synthesizes heterogeneous sources but does not include a new empirical experiment or meta-analysis.
- Some reference details are approximate where the corpus provided only partial bibliographic metadata.
- The benchmark-selection discussion remains conceptual because the corpus lacks an explicit decision framework with quantitative trade-off weights.
- Faithfulness claims are summarized from source descriptions rather than re-measured on shared protocols.
- Several benchmark resources are described at a high level, but licensing and reproducibility details are not uniform across sources.
