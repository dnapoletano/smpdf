/*******************************************
 * A Simple APPLgrid python wrapper
 * S. Carrazza - April 2015
 ********************************************/

#include <Python.h>
#include <LHAPDF/LHAPDF.h>
#include <appl_grid/appl_grid.h>
using std::vector;
using std::cout;
using std::endl;

// I hate singletons - sc
appl::grid *_g = nullptr;
vector<LHAPDF::PDF*> _pdfs;
int _imem = 0;

extern "C" void evolvepdf_(const double& x,const double& Q, double* pdf)
{  
  for (int i = 0; i < 13; i++) 
    {
      const int id = i-6;
      pdf[i] = _pdfs[_imem]->xfxQ(id, x, Q);
    }
}

extern "C" double alphaspdf_(const double& Q)
{
  return _pdfs[_imem]->alphasQ(Q);
}

static PyObject* py_initpdf(PyObject* self, PyObject* args)
{
  char* setname;
  PyArg_ParseTuple(args, "s", &setname);
  
  for (int i = 0; i < (int) _pdfs.size(); i++)
    if (_pdfs[i]) delete _pdfs[i];
  _pdfs.clear();

  _pdfs = LHAPDF::mkPDFs(setname);
  _imem = 0;

  return Py_BuildValue("");
}

static PyObject* py_pdfreplica(PyObject* self, PyObject* args)
{
  int nrep;  
  PyArg_ParseTuple(args, "i", &nrep);
  _imem = nrep;

  return Py_BuildValue("");
}

static PyObject* py_initobs(PyObject* self, PyObject* args)
{  
  char *file;
  PyArg_ParseTuple(args,"s", &file);
    
  if (_g) delete _g;
  _g = new appl::grid(file);  

  return Py_BuildValue("");
}

static PyObject* py_convolute(PyObject* self, PyObject* args)
{  
  int pto;
  PyArg_ParseTuple(args,"i", &pto);
    
  if (!_g) exit(-1);  
  vector<double> xsec = _g->vconvolute(evolvepdf_,alphaspdf_,pto);

  PyObject *out = PyList_New(xsec.size());
  for (int i = 0; i < (int) xsec.size(); i++)
    PyList_SET_ITEM(out, i, PyFloat_FromDouble(xsec[i]));

  return out;
}

static PyMethodDef applwrap_methods[] = {
  {"initpdf", py_initpdf, METH_VARARGS},
  {"pdfreplica", py_pdfreplica, METH_VARARGS},
  {"initobs", py_initobs, METH_VARARGS},
  {"convolute", py_convolute, METH_VARARGS},
  {NULL, NULL}
};

extern "C" void initapplwrap()
{
  (void) Py_InitModule("applwrap", applwrap_methods);
}