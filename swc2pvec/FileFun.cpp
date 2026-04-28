/*
 * FileFun.cpp
 *
 *  Created on: Jan 16, 2016
 *      Author: Yanjie
 */
#include "FileFun.h"

/*
 *get all file names with path from {path}. and save them to {files}. exd is the file extension (.txt, .swc)
 */
void getFiles( string path, string exd, vector<string>& files )
{

	long   hFile   =   0;

	DIR * pDir;
	struct dirent* ptr;

	string pathName, exdName;

	if (0 != strcmp(exd.c_str(), ""))
	{
		exdName = "/*." + exd;
	}
	else
	{
		exdName = "/*";
	}

	if (!(pDir = opendir(path.c_str()))){
		cout << " Folder doesn't Exist! " << endl;
		return ;
	}

	while ((ptr = readdir(pDir))!= 0 ) {
			string thefname = ptr->d_name;
			if (strcmp(ptr->d_name, "." ) != 0 && strcmp(ptr->d_name, ".." ) != 0 && thefname.at(0) != ' '){
				files.push_back(path + ptr-> d_name);
				//files.push_back(path + "/" + ptr-> d_name);
	   }
	}
	closedir(pDir);

}

int getIndex(string fileName){
	int slashIndex = fileName.find_last_of('/');
	string name = fileName.substr(slashIndex+1);
	int underscoreIndex = name.find_first_of('_');
	int index = atoi(name.substr(0,underscoreIndex).c_str());
	return index;
}

vector<string> getFixIndexFiles(vector<string> files){
	vector<string> filesFixIndex;
	filesFixIndex.resize(files.size());
	for(unsigned int i=0;i<files.size();i++){
		string next = files[i];
		int index = getIndex(next);
		filesFixIndex[index-1] = next;
	}
//	for(size_t i=0;i<files.size();i++){
//		cout<<filesFixIndex[i]<<endl;
//	}
	return filesFixIndex;
}

void readMat(string fileName,vector<vector<double> > &distanceMat){
	std::ifstream ifs;
	ifs.open(fileName.c_str());
	unsigned int size;
	ifs>>size;
	ifs>>size;
	distanceMat.resize(size);
	for (size_t i = 0; i < size; ++i){
		distanceMat[i].resize(size);
	}
	double next;
	for(size_t i = 0;i<size;i++){
		for(size_t j = 0;j<size;j++){
			ifs>>next;
			distanceMat[i][j] = next;
		}
	}
	ifs.close();
	ifs.clear();
}
