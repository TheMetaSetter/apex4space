## current challenge(s)
...

## new decisions as user stories
as [a maintainer, a student, an analyst, ...], I want code to [...].

code and tests must not import or call another module's underscore-prefixed function. tests must check behavior through public interfaces.

## instructions
start by re-explain to yourself my decisions and detect unclear details within the decisions above. then, read user stories within `documents/specs/` folder and ask clarifying questions if needed to gather more details from me.

after gather all details from me, to implement the new decisions above, please follow the procedure we established. do not propose design before executing the procedure. read [1_research_prompt.md](prompts/primitive_prompts/1_research_prompt.md), papers under `baselines_catalog/papers/`, and detect minimal lines of code in `tsad-lib/` need modifications, re-writing. then, you can propose 6 dinstinct, well-structured and minimal alternative designs supposing we can re-write parts of codebase. because re-writing code is cheap and test-driven development is effective, choose 1 design can be tested and mocked, in distinct cases, easily and in terms of individual unit test and in terms of integration test.

you should pick 1 simple decision-making framework such as MECE decision tree or Eisenhower matrix or else to choose a design yourself, on behalf of me. questions to build MECE decision tree must challenge all designs, even if you have internally chosen 1 of those designs, or not.

make sure to spawn 3 subagents and ask them to critically think against your own choice before re-iterate if needed or coming up with 1 final choice, at least 6 times. the test suit should always be minimal and simple as much as possible while being able to stress-test the codebase. remember to always write test cases before start implementing. read [2_plan_prompt.md](prompts/primitive_prompts/2_plan_prompt.md) and write minimal high-level phases of execution. read [3_structure_prompt.md](prompts/primitive_prompts/3_structure_prompt.md) and write minimal sequential stages within each phase. read [4_detail_prompt.md](prompts/primitive_prompts/4_detail_prompt.md) and write indivisible atomic steps within each stage. each atomic step is a markdown checklist item. thanks very much for your dedication.

## outputs
#### before my approval of execution plan
1. detailed runtime flow of each method within this library, from receiving input data to make decision on abnormality of a data point.
2. detailed runtime flow when experiment involves a lot of different methods and their ablation variants with target to comparing performance based on pre-defined metrics. the api must be notebook friendly and easy-to-use for high-school students, and general programmers also. the runtime flow starts from receiving data to make decision on abnormality of a data point, generate checkpoints and final reporting tables.
3. detailed runtime flow for cases of interrupted offline runs and resume.
4. detailed runtime flow for cases of interrupted batches and resume.
5. detailed execution plan to implement chosen design written in simple English words and minimal sentences.
6. detailed description of artifacts, checkpoints and statistics saved during and after runs, batch of runs and whole experiments.

- you should document all 6 things above as markdown documents. respond to me in simple words and minimal sentences in chat UI.
- all markdown documents should be written using simple words, minimal sentences and paragraphs similar to telling a story.
#### after my approval of execution plan
- codebases representing fully implemented decisions and goals.
- 2 bash scripts for each batch of runs. there are total 3 batches of runs using 1 GPU per batch and CPU cores are evenly distributed among batches. 2 final bash script to run all smoke batches and all wet batches. 1 bash script to run all offline runs and 1 bash script to run all online runs.

## goals of codebase
- goal 1 is to keep all code, documents and scripts within this codebase minimal as much as possible, with the assumption of re-writing parts of codebase is cheap and test-driven development is effective.
- goal 2 is to setup a strictly fair environment to experiment different baselines against the main method variants in both offline pre-training and online TTA phases.
- goal 3 is to have a high-school-student-friendly API to help everyone can import and use them easily in Jupyter notebooks.
- goal 4 is to ensure outputs can be uploaded each 30 minutes onto wandb and kaggle dataset which helps retain experimental results even in remote server crash.