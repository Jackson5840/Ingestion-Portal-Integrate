# swc2pvec service API
Adaption of original [Neurontools source code](https://github.com/Nevermore520/NeuronTools) to function as a Dockerized service.   
The following methods are provided:

## /clearpvecs
Clear previously submitted files

## /sendfile [POST]
Requires swc file as POST payload

## /calcpvecs
Will calculate sent pvecs

## /getjson
Fetch calculated pvecs as JSON with following structure for each neuron with name *neuronname*
```json
{"pvecs": 
  {"[neuronname]": 
    {
            "distance": "[calculated distance]",
            "Sfactor": "[calculated scaling factor]",
            "vector": "[calculated coeff vector"]
    }
  }
}
```
## /download-zip
Zips calculated pvecs and returns as zip file

Deployed and callable at with http://cng-nmo-main.orc.gmu.edu/swc2pvec/ as API root.


