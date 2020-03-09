# 1. Install using a conda virtual environment

# create virtual environment

conda create -n [ENV_NAME] python=3.7
conda activate [ENV_NAME]


# 2. Install requirements
pip install -r requirements.txt 

# 3. Install spacy corpus

python -m spacy download en_core_web_sm


# 4. Run
PYTHONPATH="." python scripts/evaluate_predictions.py --dataset_file=old_data_dev_low_level.csv --preds_file=old_data_dev_low_level_preds.csv --no_cache --output_file_base=old_data_full --metrics exact_match sari normalized_exact_match