# Literature Review Plan

## Purpose and structure

The literature review must establish the problem, identify a justified research gap, support the benchmark method and critically evaluate evidence. It should not become a source-by-source catalogue. **Taken from the Research Methods material** — `2.1 LitSurveys.pdf`, pp. 3–5 and 42–57; `LiteratureReviews.pdf`, pp. 3–8.

## Recommended chapter structure

1. **Introduction and review protocol**
   - Scope, safety boundary, databases, dates, inclusion/exclusion criteria and search terms.
2. **Language-model chatbots in mental-health-adjacent contexts**
   - Uses, known limitations, non-clinical boundary and why generic chatbots need evaluation.
3. **Psychosis-related conversational risk and epistemic reinforcement**
   - Clearly distinguish emerging concern, association and demonstrated causal effect.
4. **Sycophancy, over-agreement and dependence-related conversational behaviours**
   - Mechanisms, prompt sensitivity and relevant behavioural definitions.
5. **Multi-turn chatbot safety and LLM evaluation**
   - Why a multi-turn protocol is needed; limits of single-turn benchmark claims.
6. **Benchmark and synthetic-scenario design**
   - Controls, representativeness, protocol locking, scenario provenance and release risk.
7. **Human annotation and automated evaluation**
   - Rubrics, inter-rater agreement, LLM-as-a-judge, calibration and judge bias.
8. **Validity, reproducibility, ethics and governance**
   - Construct validity, data protection, auditability, researcher wellbeing and safeguards.
9. **Synthesis and research gap**
   - The benchmark contribution, remaining limitations and resulting research questions.

This thematic structure is **adapted from the Research Methods material** — `2.1 LitSurveys.pdf`, pp. 49–57. The chapter topics are **your additional recommendation**.

## Structured search protocol

### Databases and sources

Use ACM Digital Library, IEEE Xplore, Scopus, Web of Science, PubMed/Medline, PsycINFO where available, and backward/forward citation searching. The librarian session specifically recommends library databases, ACM, IEEE, Scopus/Web of Science, abstract screening and citation searching. **Taken from the Research Methods material** — `COP500_Research methods_C Greasley_2025.pptx`, slides 5, 21–27.

### Concepts and draft query blocks

| Concept | Example synonyms |
|---|---|
| Chatbot/model | `"large language model" OR LLM OR chatbot OR "conversational AI"` |
| Safety behaviour | `safety OR sycophancy OR "belief reinforcement" OR validation OR escalation OR dependency` |
| Multi-turn evaluation | `"multi-turn" OR dialogue OR conversation OR benchmark OR evaluation OR annotation` |
| Clinical context | `psychosis OR delusion* OR "reality testing" OR "mental health"` |

Example query:

```text
("large language model" OR LLM OR chatbot)
AND (psychosis OR delusion* OR "reality testing")
AND (safety OR validation OR reinforcement OR sycophancy)
AND (evaluation OR benchmark OR annotation OR "multi-turn")
```

Record the exact query, database, date, result count, screening decision and reason for exclusion in a search log. **Adapted from the Research Methods material** — `2.1 LitSurveys.pdf`, pp. 18–23; `COP500_Research methods_C Greasley_2025.pptx`, slides 4–8.

### Inclusion and exclusion criteria

Include peer-reviewed papers, high-quality systematic reviews, benchmark papers and official governance guidance that:

- address LLM/chatbot interaction, safety, multi-turn evaluation, relevant annotation methods or safeguards;
- describe a method sufficiently to evaluate it; and
- are relevant to the defined non-clinical benchmark scope.

Exclude unsourced media reports as primary evidence, papers only about diagnosis/treatment efficacy, generic opinion pieces without an assessable method, and studies that require reproducing unsafe content beyond the approved benchmark boundary.

**Your additional recommendation.** Use the PROMPT framework—Presentation, Relevance, Objectivity, Method, Provenance and Timeliness—to assess uncertain sources. **Taken from the Research Methods material** — `COP500_Research methods_C Greasley_2025.pptx`, slide 34.

## Evidence matrix for each included source

For each paper, record:

```text
Citation | claim supported | study design | population/data | model/version |
prompt protocol | outcome/rubric | controls | key result | limitation |
relevance to this benchmark | quality/PROMPT notes
```

This converts reading into a critical review rather than a bibliography. **Adapted from the Research Methods material** — `2.1 LitSurveys.pdf`, pp. 25–32 and 56–63.

## Claims that need strong evidence

The following must not be asserted from anecdotes, social-media posts or a single paper:

- prevalence of harmful chatbot behaviour;
- causal claims that chatbots induce or worsen psychosis;
- comparative safety claims about named models;
- claims of clinical effectiveness, diagnosis or treatment;
- generalisation from synthetic conversations to real users;
- suitability of an automated judge as a replacement for human annotation.

**Your additional recommendation.** It follows the material's requirement to examine evidence critically and limit generalisations. `1.3 Research.pdf`, p. 19; `2.1 LitSurveys.pdf`, pp. 25–32.

## Verified external starting sources

These are **External verified sources**, not course materials. They are starting points, not a complete literature review. Verify final citation formatting, version and access route in the university library before submission.

- Sharma, M. et al. (2023), *Towards Understanding Sycophancy in Language Models*. arXiv:2310.13548. https://arxiv.org/abs/2310.13548
- Zheng, L. et al. (2023), *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*. arXiv:2306.05685. https://arxiv.org/abs/2306.05685
- World Health Organization (2024), *Ethics and governance of artificial intelligence for health: Guidance on large multi-modal models*. https://www.who.int/publications/b/70584
- Olisaeloka, L., Nunez, J.-J., Vigo, D. V. and Ng, R. (2026), *Artificial intelligence (AI) psychosis: mechanisms, clinical risks and safety considerations in generative AI chatbots*. BJPsych Open. DOI: 10.1192/bjo.2026.12021. https://pubmed.ncbi.nlm.nih.gov/42273786/
- Shen, E. et al. (2026), *Evaluation of Large Language Model Chatbot Responses to Psychotic Prompts*. JAMA Psychiatry. DOI: 10.1001/jamapsychiatry.2026.0249. https://pubmed.ncbi.nlm.nih.gov/41292629/

Do not use the last two sources to make causal claims; they should be critically assessed for sample, prompt design, model versions, outcome definition and limits. **Your additional recommendation.**

## References found in supplied material that are methodologically useful

- `2.1 LitSurveys.pdf`, p. 70, cites Blaxter, Hughes & Tight, *How to Research*; Rudestam & Newton, *Surviving Your Dissertation*; and other search/research-method texts. These are **Taken from the Research Methods material** and require library verification before citation.
- `3.1 WritingReports.pdf`, p. 51, cites Levin, *Excellent Dissertations!* and writing/presentation texts. These are **Taken from the Research Methods material** and require library verification before citation.
- `Pena_Bias_in_Multimodal_AI_Testbed_for_Fair_Automatic_Recruitment_CVPRW_2020_paper.pdf` is a supplied precedent for synthetic benchmark protocols, but it concerns recruitment fairness rather than chatbot/mental-health safety. **Taken from the supplied coursework material.**

