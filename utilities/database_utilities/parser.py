from byakugan.base import Byakugan

class ModelsParser(Byakugan):
	# for python models
	def get_all_models_path(self):
		self.models_path_list = [path for path, dir_name, file in os.walk(self.project_path) for file_name in file if file_name=="models.py"]
		return self.models_path_list
 
	def get_all_fields_in_models(self):
		self.models_data_and_type_dict = dict()
			

