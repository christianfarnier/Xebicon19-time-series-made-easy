from main import main


def test_main():
    bool_dict = {"preprocess_data": False,
                 "train_deepar": False,
                 "train_prophet": False,
                 "evaluate": False,
                 "multiple_deepar_trainings": False,
                 "run_deepar_stability_study": False,
                 "run_arima_training": True}
    main(bool_dict)
